import logging
import queue
import threading
import time

import iso8583

from router.trace import TraceRecorder
from router.upstream import write_upstream
from shared.ims_connect import build_frame

logger = logging.getLogger(__name__)

_STAN_MODULUS = 1_000_000
_RESPONSE_MTIS = ("0110", "0130", "0430")


class PendingEntry:
    __slots__ = ("up_conn", "up_write_lock", "upstream_stan", "created_at", "started_at")

    def __init__(self, up_conn, up_write_lock, upstream_stan, created_at, started_at=None):
        self.up_conn = up_conn
        self.up_write_lock = up_write_lock
        self.upstream_stan = upstream_stan
        self.created_at = created_at
        # Distinct from created_at (set once this entry is added to _pending, i.e. after crypto
        # + right before the downstream send - used for the TTL reaper and downstream_rtt).
        # started_at is the true transaction start (RoutedMessage.enqueued_at, before queue wait
        # and the upstream-leg crypto call) - used for the end-to-end "total" latency bucket.
        self.started_at = started_at if started_at is not None else created_at


class RoutedMessage:
    __slots__ = ("req", "up_conn", "up_write_lock", "up_addr", "raw", "enqueued_at")

    def __init__(self, req, up_conn, up_write_lock, up_addr, raw=b"", enqueued_at=None):
        self.req = req
        self.up_conn = up_conn
        self.up_write_lock = up_write_lock
        self.up_addr = up_addr
        self.raw = raw
        self.enqueued_at = enqueued_at


class Dispatcher:
    """Worker pool. Routes 0100 upstream -> crypto -> downstream.
    Routes 0110/0130/0430 downstream -> upstream (STAN lookup)."""

    def __init__(self, cfg, downstream, crypto, spec, stats, reconnect_event, upstream_spec=None):
        self.cfg = cfg
        self.downstream = downstream
        self.crypto = crypto
        self.spec = spec
        # Upstream-facing leg can speak a different ISO 8583 encoding than the downstream leg
        # (e.g. router_2's EBCDIC partner spec vs the shared downstream_host's ASCII spec) -
        # defaults to `spec` so single-spec configs (router_1, and every config predating this)
        # behave exactly as before.
        self.upstream_spec = upstream_spec if upstream_spec is not None else spec
        self.stats = stats
        self.reconnect_event = reconnect_event

        self.trace = TraceRecorder()

        self._queue = queue.Queue(maxsize=cfg.queue_maxsize)
        self._response_queue = queue.Queue(maxsize=cfg.queue_maxsize)
        self._pending = {}
        self._pending_lock = threading.Lock()
        self._stan_counter = 0
        self._stan_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_threads = []
        self._response_worker_threads = []
        self._reaper_thread = None

    def _next_stan(self) -> str:
        with self._stan_lock:
            self._stan_counter = (self._stan_counter + 1) % _STAN_MODULUS
            return str(self._stan_counter).zfill(6)

    def start(self) -> None:
        for i in range(self.cfg.worker_threads):
            t = threading.Thread(target=self._worker_loop, name=f"worker-{i}", daemon=True)
            t.start()
            self._worker_threads.append(t)
        for i in range(self.cfg.response_worker_threads):
            t = threading.Thread(
                target=self._response_worker_loop, name=f"response-worker-{i}", daemon=True
            )
            t.start()
            self._response_worker_threads.append(t)
        self._reaper_thread = threading.Thread(
            target=self._pending_reaper, name="pending-reaper", daemon=True
        )
        self._reaper_thread.start()

    def submit(self, msg: RoutedMessage) -> None:
        msg.enqueued_at = time.monotonic()
        self._queue.put(msg)
        qsize = self._queue.qsize()
        self.stats.set_gauge("queue_depth", qsize)
        logger.debug("dispatcher: queued mti=%s (queue_depth=%d)", msg.req.get("t"), qsize)

    def submit_response(self, resp: dict, raw: bytes = b"") -> None:
        """Enqueues a downstream response (0110/0130/0430) for handling by the response
        worker pool, instead of processing it inline on the caller's thread. This keeps the
        0110 leg's crypto call (validate_0110) from being a single-threaded bottleneck that's
        entirely separate from - and doesn't have to compete with - the 0100 leg's queue."""
        self._response_queue.put((resp, raw))
        qsize = self._response_queue.qsize()
        self.stats.set_gauge("response_queue_depth", qsize)
        logger.debug("dispatcher: queued response mti=%s (response_queue_depth=%d)", resp.get("t"), qsize)

    def _worker_loop(self) -> None:
        while True:
            msg = self._queue.get()
            self.stats.set_gauge("queue_depth", self._queue.qsize())
            if msg is None:
                return
            if msg.enqueued_at is not None:
                self.stats.record_latency("queue_wait", (time.monotonic() - msg.enqueued_at) * 1000)
            try:
                self._process(msg)
            except OSError:
                logger.warning("downstream send failed while dispatching; triggering reconnect")
                self.reconnect_event.set()
            except Exception:
                logger.exception("unexpected error processing dispatched message")

    def _response_worker_loop(self) -> None:
        while True:
            item = self._response_queue.get()
            self.stats.set_gauge("response_queue_depth", self._response_queue.qsize())
            if item is None:
                return
            resp, raw = item
            try:
                self.handle_response(resp, raw=raw)
            except Exception:
                logger.exception("unexpected error processing dispatched response")

    def _process(self, msg: RoutedMessage) -> None:
        req = msg.req
        mti = req.get("t")
        pan = req.get("2", "")
        upstream_stan = req.get("11", "")

        router_stan = self._next_stan()
        tracing = self.trace.start(router_stan, upstream_stan, pan, mti, msg.raw)

        fwd = dict(req)
        if mti == "0100":
            crypto_start = time.monotonic()
            result = self.crypto.validate("validate_0100", pan, req.get("47", ""), router_stan=router_stan)
            crypto_ms = (time.monotonic() - crypto_start) * 1000
            self.stats.record_latency("crypto_rtt", crypto_ms)
            if tracing:
                self.trace.hop(router_stan, "crypto_call", crypto_ms=round(crypto_ms, 3), enriched=bool(result))
            if result:
                fwd["47"] = result
        fwd["11"] = router_stan

        encoded, _ = iso8583.encode(fwd, self.spec)
        if tracing:
            self.trace.hop(router_stan, "downstream_send", raw=bytes(encoded))

        with self._pending_lock:
            if router_stan in self._pending:
                logger.error(
                    "router_stan %s still outstanding; overwriting pending entry",
                    router_stan, extra={"router_stan": router_stan},
                )
            self._pending[router_stan] = PendingEntry(
                up_conn=msg.up_conn,
                up_write_lock=msg.up_write_lock,
                upstream_stan=upstream_stan,
                created_at=time.monotonic(),
                started_at=msg.enqueued_at,
            )
            pending_count = len(self._pending)
        self.stats.set_gauge("pending_count", pending_count)

        frame = build_frame(
            0x00, self.cfg.downstream.irm_id, self.cfg.downstream.client_id, mti=fwd["t"], data=bytes(encoded)
        )
        self.downstream.send(frame)
        self.stats.record_sent()
        logger.debug(
            "dispatcher: forwarded mti=%s to downstream, upstream_stan=%s router_stan=%s",
            mti, upstream_stan, router_stan, extra={"router_stan": router_stan},
        )

    def handle_response(self, resp: dict, raw: bytes = b"") -> None:
        mti = resp.get("t")
        if mti == "0810":
            return
        if mti not in _RESPONSE_MTIS:
            logger.warning("unexpected response MTI from downstream: %s", mti)
            return

        router_stan = resp.get("11", "")
        self.trace.hop(router_stan, "downstream_recv", raw=raw)
        tracing = self.trace.is_tracing(router_stan)

        now = time.monotonic()
        with self._pending_lock:
            entry = self._pending.pop(router_stan, None)
            pending_count = len(self._pending)
        self.stats.set_gauge("pending_count", pending_count)
        if entry is None:
            logger.warning(
                "no pending entry for router_stan %s", router_stan, extra={"router_stan": router_stan}
            )
            if tracing:
                self.trace.finish(router_stan)
            return
        self.stats.record_latency("downstream_rtt", (now - entry.created_at) * 1000)

        fwd = dict(resp)
        fwd["11"] = entry.upstream_stan
        if mti == "0110":
            pan = resp.get("2", "")
            crypto_start = time.monotonic()
            result = self.crypto.validate("validate_0110", pan, resp.get("47", ""), router_stan=router_stan)
            crypto_ms = (time.monotonic() - crypto_start) * 1000
            self.stats.record_latency("crypto_rtt", crypto_ms)
            if tracing:
                self.trace.hop(router_stan, "crypto_call", crypto_ms=round(crypto_ms, 3), enriched=bool(result))
            if result:
                fwd["47"] = result

        encoded, _ = iso8583.encode(fwd, self.upstream_spec)
        if tracing:
            self.trace.hop(router_stan, "upstream_send", raw=bytes(encoded))
        try:
            with entry.up_write_lock:
                write_upstream(entry.up_conn, bytes(encoded), self.cfg.upstream)
            self.stats.record_sent()
            logger.debug(
                "dispatcher: forwarded mti=%s to upstream, router_stan=%s upstream_stan=%s",
                mti, router_stan, entry.upstream_stan, extra={"router_stan": router_stan},
            )
        except OSError:
            # entry.up_conn can be closed by session teardown racing this write.
            logger.warning(
                "failed to write response upstream for stan %s",
                entry.upstream_stan, extra={"router_stan": router_stan},
            )
        self.stats.record_latency("total", (time.monotonic() - entry.started_at) * 1000)
        if tracing:
            self.trace.finish(router_stan)

    def _pending_reaper(self) -> None:
        while not self._stop_event.wait(1.0):
            now = time.monotonic()
            expired = []
            with self._pending_lock:
                for stan, entry in list(self._pending.items()):
                    if now - entry.created_at > self.cfg.pending_ttl_seconds:
                        expired.append((stan, entry))
                for stan, _entry in expired:
                    del self._pending[stan]
                pending_count = len(self._pending)
            if expired:
                self.stats.set_gauge("pending_count", pending_count)

            for stan, entry in expired:
                logger.warning(
                    "pending entry %s expired after %ds; sending local decline",
                    stan, self.cfg.pending_ttl_seconds, extra={"router_stan": stan},
                )
                decline = {"t": "0110", "11": entry.upstream_stan, "39": "91"}
                try:
                    encoded, _ = iso8583.encode(decline, self.upstream_spec)
                    with entry.up_write_lock:
                        write_upstream(entry.up_conn, bytes(encoded), self.cfg.upstream)
                    self.stats.record_sent()
                except OSError:
                    logger.warning(
                        "failed to write expiry decline for stan %s",
                        entry.upstream_stan, extra={"router_stan": stan},
                    )

    def pending_snapshot(self) -> list:
        """Read-only view of in-flight transactions (downstream request sent, no response yet)
        for live diagnosis - e.g. "why is this router stuck", without waiting for the
        pending_ttl_seconds reaper to expire and decline them. Sorted oldest-first so a stuck
        transaction sorts to the top."""
        now = time.monotonic()
        with self._pending_lock:
            entries = [
                {
                    "router_stan": stan,
                    "upstream_stan": entry.upstream_stan,
                    "age_seconds": round(now - entry.created_at, 3),
                }
                for stan, entry in self._pending.items()
            ]
        entries.sort(key=lambda e: e["age_seconds"], reverse=True)
        return entries

    def purge(self) -> dict:
        dropped_queue = 0
        while True:
            try:
                self._queue.get_nowait()
                dropped_queue += 1
            except queue.Empty:
                break
        dropped_response_queue = 0
        while True:
            try:
                self._response_queue.get_nowait()
                dropped_response_queue += 1
            except queue.Empty:
                break
        with self._pending_lock:
            dropped_pending = len(self._pending)
            self._pending.clear()
        self.stats.set_gauge("queue_depth", self._queue.qsize())
        self.stats.set_gauge("response_queue_depth", self._response_queue.qsize())
        self.stats.set_gauge("pending_count", 0)
        return {
            "dropped_queue": dropped_queue,
            "dropped_response_queue": dropped_response_queue,
            "dropped_pending": dropped_pending,
        }

    def drain_and_stop(self) -> None:
        self._stop_event.set()
        for _ in self._worker_threads:
            self._queue.put(None)
        for _ in self._response_worker_threads:
            self._response_queue.put(None)
        for t in self._worker_threads:
            t.join(timeout=5)
        for t in self._response_worker_threads:
            t.join(timeout=5)
        if self._reaper_thread is not None:
            self._reaper_thread.join(timeout=5)

        # Session teardown (upstream or downstream disconnect, reconnect) previously discarded
        # any still-in-flight transactions with zero trace - unlike purge(), which reports
        # dropped_pending, this path left no log line explaining why a transaction just
        # vanished. There's nothing to *do* about them (the upstream client that would receive
        # a decline is already gone), but a live-diagnosis session needs the record.
        with self._pending_lock:
            dropped = list(self._pending.items())
            self._pending.clear()
        for stan, entry in dropped:
            logger.warning(
                "session torn down with router_stan %s still pending (upstream_stan=%s); abandoning",
                stan, entry.upstream_stan, extra={"router_stan": stan},
            )
        if dropped:
            logger.warning("session teardown abandoned %d pending transaction(s)", len(dropped))
            self.stats.set_gauge("pending_count", 0)

        abandoned_traces = self.trace.abandon_in_progress()
        if abandoned_traces:
            logger.warning("session teardown left %d in-progress trace(s) incomplete", len(abandoned_traces))

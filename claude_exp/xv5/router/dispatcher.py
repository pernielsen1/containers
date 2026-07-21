import logging
import queue
import threading
import time

import iso8583

from router.upstream import write_upstream
from shared.ims_connect import build_frame

logger = logging.getLogger(__name__)

_STAN_MODULUS = 1_000_000
_RESPONSE_MTIS = ("0110", "0130", "0430")


class PendingEntry:
    __slots__ = ("up_conn", "up_write_lock", "upstream_stan", "created_at")

    def __init__(self, up_conn, up_write_lock, upstream_stan, created_at):
        self.up_conn = up_conn
        self.up_write_lock = up_write_lock
        self.upstream_stan = upstream_stan
        self.created_at = created_at


class RoutedMessage:
    __slots__ = ("req", "up_conn", "up_write_lock", "up_addr")

    def __init__(self, req, up_conn, up_write_lock, up_addr):
        self.req = req
        self.up_conn = up_conn
        self.up_write_lock = up_write_lock
        self.up_addr = up_addr


class Dispatcher:
    """Worker pool. Routes 0100 upstream -> crypto -> downstream.
    Routes 0110/0130/0430 downstream -> upstream (STAN lookup)."""

    def __init__(self, cfg, downstream, crypto, spec, stats, reconnect_event):
        self.cfg = cfg
        self.downstream = downstream
        self.crypto = crypto
        self.spec = spec
        self.stats = stats
        self.reconnect_event = reconnect_event

        self._queue = queue.Queue(maxsize=cfg.queue_maxsize)
        self._pending = {}
        self._pending_lock = threading.Lock()
        self._stan_counter = 0
        self._stan_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_threads = []
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
        self._reaper_thread = threading.Thread(
            target=self._pending_reaper, name="pending-reaper", daemon=True
        )
        self._reaper_thread.start()

    def submit(self, msg: RoutedMessage) -> None:
        self._queue.put(msg)
        self.stats.set_gauge("queue_depth", self._queue.qsize())

    def _worker_loop(self) -> None:
        while True:
            msg = self._queue.get()
            self.stats.set_gauge("queue_depth", self._queue.qsize())
            if msg is None:
                return
            try:
                self._process(msg)
            except OSError:
                logger.warning("downstream send failed while dispatching; triggering reconnect")
                self.reconnect_event.set()
            except Exception:
                logger.exception("unexpected error processing dispatched message")

    def _process(self, msg: RoutedMessage) -> None:
        req = msg.req
        mti = req.get("t")
        pan = req.get("2", "")
        upstream_stan = req.get("11", "")

        router_stan = self._next_stan()

        fwd = dict(req)
        if mti == "0100":
            result = self.crypto.validate("validate_0100", pan, req.get("47", ""))
            if result:
                fwd["47"] = result
        fwd["11"] = router_stan

        encoded, _ = iso8583.encode(fwd, self.spec)

        with self._pending_lock:
            if router_stan in self._pending:
                logger.error("router_stan %s still outstanding; overwriting pending entry", router_stan)
            self._pending[router_stan] = PendingEntry(
                up_conn=msg.up_conn,
                up_write_lock=msg.up_write_lock,
                upstream_stan=upstream_stan,
                created_at=time.monotonic(),
            )
            pending_count = len(self._pending)
        self.stats.set_gauge("pending_count", pending_count)

        frame = build_frame(
            0x00, self.cfg.downstream.irm_id, self.cfg.downstream.client_id, mti=fwd["t"], data=bytes(encoded)
        )
        self.downstream.send(frame)
        self.stats.record_sent()

    def handle_response(self, resp: dict) -> None:
        mti = resp.get("t")
        if mti == "0810":
            return
        if mti not in _RESPONSE_MTIS:
            logger.warning("unexpected response MTI from downstream: %s", mti)
            return

        router_stan = resp.get("11", "")
        with self._pending_lock:
            entry = self._pending.pop(router_stan, None)
            pending_count = len(self._pending)
        self.stats.set_gauge("pending_count", pending_count)
        if entry is None:
            logger.warning("no pending entry for router_stan %s", router_stan)
            return

        fwd = dict(resp)
        fwd["11"] = entry.upstream_stan
        if mti == "0110":
            pan = resp.get("2", "")
            result = self.crypto.validate("validate_0110", pan, resp.get("47", ""))
            if result:
                fwd["47"] = result

        encoded, _ = iso8583.encode(fwd, self.spec)
        try:
            with entry.up_write_lock:
                write_upstream(entry.up_conn, bytes(encoded), self.cfg.upstream)
            self.stats.record_sent()
        except OSError:
            # entry.up_conn can be closed by session teardown racing this write.
            logger.warning("failed to write response upstream for stan %s", entry.upstream_stan)

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
                    stan, self.cfg.pending_ttl_seconds,
                )
                decline = {"t": "0110", "11": entry.upstream_stan, "39": "91"}
                try:
                    encoded, _ = iso8583.encode(decline, self.spec)
                    with entry.up_write_lock:
                        write_upstream(entry.up_conn, bytes(encoded), self.cfg.upstream)
                    self.stats.record_sent()
                except OSError:
                    logger.warning("failed to write expiry decline for stan %s", entry.upstream_stan)

    def purge(self) -> dict:
        dropped_queue = 0
        while True:
            try:
                self._queue.get_nowait()
                dropped_queue += 1
            except queue.Empty:
                break
        with self._pending_lock:
            dropped_pending = len(self._pending)
            self._pending.clear()
        self.stats.set_gauge("queue_depth", self._queue.qsize())
        self.stats.set_gauge("pending_count", 0)
        return {"dropped_queue": dropped_queue, "dropped_pending": dropped_pending}

    def drain_and_stop(self) -> None:
        self._stop_event.set()
        for _ in self._worker_threads:
            self._queue.put(None)
        for t in self._worker_threads:
            t.join(timeout=5)
        if self._reaper_thread is not None:
            self._reaper_thread.join(timeout=5)

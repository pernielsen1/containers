import logging
import queue
import socket
import threading
import time
from dataclasses import dataclass

import iso8583

from shared.framing import write_message
from shared.ims_connect import build_frame

logger = logging.getLogger(__name__)

_STAN_MODULUS = 1_000_000
_RESPONSE_MTIS = ("0110", "0130", "0430")


@dataclass
class PendingEntry:
    up_conn: socket.socket
    up_write_lock: threading.Lock
    upstream_stan: str
    created_at: float


@dataclass
class RoutedMessage:
    req: dict
    up_conn: socket.socket
    up_write_lock: threading.Lock
    up_addr: tuple


class Dispatcher:
    """Worker pool. Routes 0100 upstream → crypto → downstream.
    Routes 0110/0130/0430 downstream → upstream (STAN lookup)."""

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

        self._workers = []
        self._reaper = None
        self._stop = threading.Event()

    def _next_stan(self) -> str:
        with self._stan_lock:
            stan = self._stan_counter
            self._stan_counter = (self._stan_counter + 1) % _STAN_MODULUS
        return str(stan).zfill(6)

    def start(self):
        for i in range(self.cfg.worker_threads):
            t = threading.Thread(target=self._worker_loop, name=f"worker-{i}", daemon=True)
            t.start()
            self._workers.append(t)

        self._reaper = threading.Thread(target=self._pending_reaper, name="pending-reaper", daemon=True)
        self._reaper.start()

    def submit(self, msg: RoutedMessage) -> None:
        # Blocking enqueue. Once the queue is at cfg.queue_maxsize this blocks the calling
        # upstream read thread — deliberate backpressure so memory stays bounded under a
        # sustained downstream/crypto outage, rather than growing the queue without limit.
        self._queue.put(msg)
        self.stats.set_gauge("queue_depth", self._queue.qsize())

    def _worker_loop(self):
        while True:
            msg = self._queue.get()
            self.stats.set_gauge("queue_depth", self._queue.qsize())
            if msg is None:
                break
            try:
                self._process(msg)
            except OSError:
                self.reconnect_event.set()
            except Exception:
                logger.exception("worker failed to process message")

    def _process(self, msg: RoutedMessage):
        req = msg.req
        mti = req.get("t")
        pan = req.get("2", "")
        upstream_stan = req.get("11", "")
        router_stan = self._next_stan()

        fwd = dict(req)
        fwd["11"] = router_stan

        if mti == "0100":
            result = self.crypto.validate("validate_0100", pan, req.get("47", ""))
            if result:
                fwd["47"] = result

        encoded, _ = iso8583.encode(fwd, self.spec)

        with self._pending_lock:
            if router_stan in self._pending:
                logger.error(
                    "router_stan %s still occupied on reuse; original caller will never get a reply",
                    router_stan,
                )
            self._pending[router_stan] = PendingEntry(
                up_conn=msg.up_conn,
                up_write_lock=msg.up_write_lock,
                upstream_stan=upstream_stan,
                created_at=time.monotonic(),
            )
            self.stats.set_gauge("pending_count", len(self._pending))

        frame = build_frame(
            0x00,
            self.cfg.downstream.irm_id,
            self.cfg.downstream.client_id,
            mti=fwd["t"],
            data=bytes(encoded),
        )
        self.downstream.send(frame)
        self.stats.record_sent()

    def handle_response(self, resp: dict):
        mti = resp.get("t")
        if mti == "0810":
            return
        if mti not in _RESPONSE_MTIS:
            logger.warning("unexpected MTI in downstream response: %s", mti)
            return

        router_stan = resp.get("11", "")
        with self._pending_lock:
            entry = self._pending.pop(router_stan, None)
            self.stats.set_gauge("pending_count", len(self._pending))

        if entry is None:
            logger.warning("no pending entry for router_stan %s (mti=%s)", router_stan, mti)
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
                write_message(entry.up_conn, bytes(encoded), self.cfg.upstream.framing.to_dict())
            self.stats.record_sent()
        except OSError:
            # The upstream connection can be closed by session teardown out from under this
            # write (called from the ds-receiver thread) — the caller already timed out or
            # will reconnect, so there's no reply path left to retry; just drop it.
            logger.warning("failed to write response for router_stan %s to upstream", router_stan)

    def purge(self) -> dict:
        # Operator-triggered, NOT part of session teardown.
        queue_dropped = 0
        while True:
            try:
                self._queue.get_nowait()
                queue_dropped += 1
            except queue.Empty:
                break
        self.stats.set_gauge("queue_depth", self._queue.qsize())

        with self._pending_lock:
            pending_dropped = len(self._pending)
            self._pending.clear()
            self.stats.set_gauge("pending_count", 0)

        return {"queue_dropped": queue_dropped, "pending_dropped": pending_dropped}

    def _pending_reaper(self):
        while not self._stop.wait(1.0):
            now = time.monotonic()
            expired = []
            with self._pending_lock:
                for router_stan, entry in list(self._pending.items()):
                    if now - entry.created_at > self.cfg.pending_ttl_seconds:
                        expired.append((router_stan, entry))
                for router_stan, _ in expired:
                    del self._pending[router_stan]
                if expired:
                    self.stats.set_gauge("pending_count", len(self._pending))

            for router_stan, entry in expired:
                logger.warning(
                    "pending entry %s expired after %ss, sending local decline",
                    router_stan,
                    self.cfg.pending_ttl_seconds,
                )
                decline = {"t": "0110", "11": entry.upstream_stan, "39": "91"}
                try:
                    encoded, _ = iso8583.encode(decline, self.spec)
                    with entry.up_write_lock:
                        write_message(entry.up_conn, bytes(encoded), self.cfg.upstream.framing.to_dict())
                    self.stats.record_sent()
                except OSError:
                    logger.warning("failed to write local decline for expired entry %s", router_stan)

    def drain_and_stop(self):
        self._stop.set()
        for _ in self._workers:
            self._queue.put(None)
        for t in self._workers:
            t.join(timeout=5)
        if self._reaper is not None:
            self._reaper.join(timeout=5)

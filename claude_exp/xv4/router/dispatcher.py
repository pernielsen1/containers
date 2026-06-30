import logging
import queue
import threading
import time
from dataclasses import dataclass

import iso8583
import iso8583.specs

from shared.ims_connect import build_frame
from shared.iso_utils import f47_decode, f47_encode

logger = logging.getLogger(__name__)


@dataclass
class PendingEntry:
    up_conn: object
    up_write_lock: threading.Lock
    upstream_stan: str
    created_at: float


@dataclass
class RoutedMessage:
    req: dict
    up_conn: object
    up_write_lock: threading.Lock
    up_addr: tuple


class Dispatcher:
    def __init__(self, cfg, downstream, crypto, spec, stats, reconnect_event):
        self._cfg = cfg
        self._downstream = downstream
        self._crypto = crypto
        self._spec = spec
        self._stats = stats
        self._reconnect_event = reconnect_event
        self._queue = queue.Queue(maxsize=cfg.queue_maxsize)
        self._pending = {}
        self._pending_lock = threading.Lock()
        self._stan_counter = 0
        self._stan_lock = threading.Lock()
        self._workers = []
        self._reaper = None
        self._stop_event = threading.Event()

    def _next_stan(self) -> str:
        with self._stan_lock:
            self._stan_counter = (self._stan_counter + 1) % 1_000_000
            return str(self._stan_counter).zfill(6)

    def start(self):
        for i in range(self._cfg.worker_threads):
            t = threading.Thread(target=self._worker, name=f"worker-{i}", daemon=True)
            t.start()
            self._workers.append(t)
        self._reaper = threading.Thread(target=self._pending_reaper, daemon=True)
        self._reaper.start()

    def submit(self, msg: RoutedMessage) -> None:
        self._queue.put(msg)
        self._stats.set_gauge("queue_depth", self._queue.qsize())

    def _worker(self):
        while True:
            msg = self._queue.get()
            self._stats.set_gauge("queue_depth", self._queue.qsize())
            if msg is None:
                break
            try:
                self._process(msg)
            except Exception:
                logger.exception("worker error processing message")

    def _process(self, msg: RoutedMessage):
        req = msg.req
        mti = req.get("t")
        pan = req.get("2", "")
        upstream_stan = req.get("11", "")

        router_stan = self._next_stan()

        fwd = dict(req)
        fwd["11"] = router_stan

        if mti == "0100":
            f47_in = req.get("47", "")
            f47_out = self._crypto.validate("validate_0100", pan, f47_in)
            if f47_out:
                fwd["47"] = f47_out

        encoded, _ = iso8583.encode(fwd, self._spec)

        entry = PendingEntry(
            up_conn=msg.up_conn,
            up_write_lock=msg.up_write_lock,
            upstream_stan=upstream_stan,
            created_at=time.monotonic(),
        )
        with self._pending_lock:
            if router_stan in self._pending:
                logger.error("STAN collision: router_stan=%s still pending; overwriting", router_stan)
            self._pending[router_stan] = entry
            self._stats.set_gauge("pending_count", len(self._pending))

        frame = build_frame(
            0x00,
            self._cfg.downstream.irm_id,
            self._cfg.downstream.client_id,
            fwd["t"],
            encoded,
        )
        try:
            self._downstream.send(frame)
            self._stats.record_sent()
        except OSError as e:
            logger.error("downstream send error: %s", e)
            self._reconnect_event.set()

    def handle_response(self, resp: dict):
        mti = resp.get("t")
        if mti == "0810":
            return
        if mti not in ("0110", "0130", "0430"):
            logger.warning("dispatcher received unexpected mti=%s", mti)
            return

        router_stan = resp.get("11", "")
        with self._pending_lock:
            entry = self._pending.pop(router_stan, None)
            self._stats.set_gauge("pending_count", len(self._pending))

        if entry is None:
            logger.warning("no pending entry for router_stan=%s mti=%s", router_stan, mti)
            return

        fwd = dict(resp)
        fwd["11"] = entry.upstream_stan

        if mti == "0110":
            pan = resp.get("2", "")
            f47_in = resp.get("47", "")
            f47_out = self._crypto.validate("validate_0110", pan, f47_in)
            if f47_out:
                fwd["47"] = f47_out

        encoded, _ = iso8583.encode(fwd, self._spec)

        from shared.framing import write_message
        from router.upstream import write_upstream

        try:
            with entry.up_write_lock:
                from shared.framing import write_message
                # write directly using the connection (it's already a socket)
                entry.up_conn.sendall(self._encode_upstream_frame(encoded))
            self._stats.record_sent()
        except OSError as e:
            logger.warning("write to upstream failed (teardown race?): %s", e)

    def _encode_upstream_frame(self, data: bytes) -> bytes:
        cfg = self._cfg.upstream
        framing = cfg.framing.to_dict()
        lf_bytes = framing["length_field_bytes"]
        lf_type = framing["length_field_type"]
        length = len(data)

        header_hex = framing.get("header_hex", "")
        header = bytes.fromhex(header_hex) if header_hex else b""

        if lf_type == "BIG_ENDIAN":
            raw_len = length.to_bytes(lf_bytes, "big")
        elif lf_type == "LITTLE_ENDIAN":
            raw_len = length.to_bytes(lf_bytes, "little")
        elif lf_type == "ASCII":
            raw_len = str(length).zfill(lf_bytes).encode("ascii")
        elif lf_type == "EBCDIC":
            raw_len = str(length).zfill(lf_bytes).encode("cp500")
        else:
            raise ValueError(f"unknown length_field_type: {lf_type}")

        return header + raw_len + data

    def _pending_reaper(self):
        while not self._stop_event.is_set():
            self._stop_event.wait(1.0)
            now = time.monotonic()
            ttl = self._cfg.pending_ttl_seconds
            expired = []
            with self._pending_lock:
                for stan, entry in list(self._pending.items()):
                    if now - entry.created_at > ttl:
                        expired.append((stan, self._pending.pop(stan)))
                if expired:
                    self._stats.set_gauge("pending_count", len(self._pending))

            for stan, entry in expired:
                logger.warning("pending entry expired stan=%s — sending decline f39=91", stan)
                decline = {
                    "t": "0110",
                    "11": entry.upstream_stan,
                    "39": "91",
                }
                try:
                    encoded, _ = iso8583.encode(decline, self._spec)
                    frame = self._encode_upstream_frame(encoded)
                    with entry.up_write_lock:
                        entry.up_conn.sendall(frame)
                    self._stats.record_sent()
                except OSError as e:
                    logger.warning("reaper write to upstream failed: %s", e)
                except Exception:
                    logger.exception("reaper encode error for stan=%s", stan)

    def purge(self) -> dict:
        dropped_pending = 0
        dropped_queue = 0

        with self._pending_lock:
            dropped_pending = len(self._pending)
            self._pending.clear()
            self._stats.set_gauge("pending_count", 0)

        while True:
            try:
                self._queue.get_nowait()
                dropped_queue += 1
            except queue.Empty:
                break
        self._stats.set_gauge("queue_depth", 0)

        logger.warning("purge: dropped %d pending + %d queued", dropped_pending, dropped_queue)
        return {"dropped_pending": dropped_pending, "dropped_queue": dropped_queue}

    def drain_and_stop(self):
        self._stop_event.set()
        for _ in self._workers:
            self._queue.put(None)
        for w in self._workers:
            w.join(timeout=5)

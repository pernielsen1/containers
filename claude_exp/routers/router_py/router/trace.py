import threading
import time
from collections import deque


class TraceRecorder:
    """On-demand, self-expiring capture of full per-hop transaction detail for live diagnosis at
    production volume - briefs/debug_trace_master.md Phase 4. Off by default: the hot path pays
    only a lock + dict-lookup per hop call site when disarmed (no wire-byte hex-encoding, no
    extra allocation), so it's safe to leave wired in permanently rather than only under a
    feature flag. Once armed via arm(), captures the next `count` transactions - optionally
    filtered to a specific upstream_stan or pan - end to end: raw wire bytes at every hop plus
    per-hop elapsed time, then auto-disarms so a capture can never accidentally run forever.
    """

    def __init__(self, max_entries: int = 50):
        self._lock = threading.Lock()
        self.armed = False
        self._remaining = 0
        self._filter_stan = None
        self._filter_pan = None
        self._entries = deque(maxlen=max_entries)
        self._in_progress = {}

    def arm(self, count: int, stan: str = None, pan: str = None) -> None:
        with self._lock:
            self._remaining = max(int(count), 0)
            self.armed = self._remaining > 0
            self._filter_stan = stan or None
            self._filter_pan = pan or None

    def start(self, router_stan: str, upstream_stan: str, pan: str, mti: str, raw: bytes) -> bool:
        """Called once per transaction, at its first hop. Returns whether this transaction is
        being traced, so callers can skip building later hop details (e.g. re-encoding bytes
        that would otherwise just be discarded) when it isn't."""
        if not self.armed:
            return False
        with self._lock:
            if not self.armed:
                return False
            if self._filter_stan and upstream_stan != self._filter_stan:
                return False
            if self._filter_pan and pan != self._filter_pan:
                return False
            self._remaining -= 1
            if self._remaining <= 0:
                self.armed = False
            self._in_progress[router_stan] = {
                "router_stan": router_stan,
                "upstream_stan": upstream_stan,
                "pan": pan,
                "mti": mti,
                "_started_at": time.monotonic(),
                "hops": [{"stage": "upstream_recv", "elapsed_ms": 0.0, "wire_hex": raw.hex()}],
            }
            return True

    def is_tracing(self, router_stan: str) -> bool:
        with self._lock:
            return router_stan in self._in_progress

    def hop(self, router_stan: str, stage: str, raw: bytes = None, **fields) -> None:
        with self._lock:
            entry = self._in_progress.get(router_stan)
            if entry is None:
                return
            elapsed_ms = (time.monotonic() - entry["_started_at"]) * 1000
            record = {"stage": stage, "elapsed_ms": round(elapsed_ms, 3)}
            if raw is not None:
                record["wire_hex"] = raw.hex()
            record.update(fields)
            entry["hops"].append(record)

    def finish(self, router_stan: str) -> None:
        with self._lock:
            entry = self._in_progress.pop(router_stan, None)
            if entry is not None:
                del entry["_started_at"]
                self._entries.append(entry)

    def abandon_in_progress(self) -> list:
        """Flushes any traces that were mid-capture into entries (marked incomplete) instead of
        leaking them silently - called from Dispatcher.drain_and_stop() so a session teardown
        mid-trace doesn't just vanish, same reasoning as the pending-transaction abandonment log
        added there."""
        with self._lock:
            abandoned = list(self._in_progress.values())
            for entry in abandoned:
                entry["incomplete"] = True
                del entry["_started_at"]
                self._entries.append(entry)
            self._in_progress.clear()
            return abandoned

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "armed": self.armed,
                "remaining": self._remaining,
                "entries": list(self._entries),
            }

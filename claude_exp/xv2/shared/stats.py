import threading
import time as _time
from collections import deque

time_func = _time.monotonic

_WINDOWS = [30, 60, 180, 1800]
_MAX_WINDOW = max(_WINDOWS)


class Stats:
    def __init__(self, yellow_threshold_seconds=None):
        self._lock = threading.Lock()
        self._sent = deque()
        self._recv = deque()
        self._sent_total = 0
        self._recv_total = 0
        self._last_recv_time = None
        self._yellow_threshold = yellow_threshold_seconds

    def record_sent(self):
        with self._lock:
            now = time_func()
            self._sent.append(now)
            self._sent_total += 1
            self._prune(self._sent, now)

    def record_recv(self):
        with self._lock:
            now = time_func()
            self._recv.append(now)
            self._recv_total += 1
            self._last_recv_time = now
            self._prune(self._recv, now)

    def _prune(self, d, now):
        cutoff = now - _MAX_WINDOW
        while d and d[0] < cutoff:
            d.popleft()

    def snapshot(self):
        with self._lock:
            now = time_func()
            result = {"sent_total": self._sent_total, "recv_total": self._recv_total}
            for w in _WINDOWS:
                cutoff = now - w
                result[f"sent_{w}s"] = sum(1 for t in self._sent if t >= cutoff)
                result[f"recv_{w}s"] = sum(1 for t in self._recv if t >= cutoff)
            if self._last_recv_time is not None:
                result["seconds_since_last_recv"] = now - self._last_recv_time
            else:
                result["seconds_since_last_recv"] = None
            if self._yellow_threshold is not None:
                result["yellow_threshold_seconds"] = self._yellow_threshold
            return result

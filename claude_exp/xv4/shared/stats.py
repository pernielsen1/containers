import threading
import time
from collections import deque


class Stats:
    WINDOWS = [30, 60, 180, 1800]

    def __init__(self, yellow_threshold_seconds=None):
        self._lock = threading.Lock()
        self._sent_times = deque()
        self._recv_times = deque()
        self._sent_total = 0
        self._recv_total = 0
        self._last_recv_time = None
        self._connections = {}
        self._gauges = {}
        self._yellow_threshold_seconds = yellow_threshold_seconds

    def set_connection(self, name: str, connected: bool):
        with self._lock:
            self._connections[name] = connected

    def set_gauge(self, name: str, value):
        with self._lock:
            self._gauges[name] = value

    def record_sent(self):
        with self._lock:
            now = time.monotonic()
            self._sent_times.append(now)
            self._sent_total += 1

    def record_recv(self):
        with self._lock:
            now = time.monotonic()
            self._recv_times.append(now)
            self._recv_total += 1
            self._last_recv_time = now

    def _count_since(self, times_deque, cutoff):
        count = 0
        for t in reversed(times_deque):
            if t >= cutoff:
                count += 1
            else:
                break
        return count

    def snapshot(self) -> dict:
        with self._lock:
            now = time.monotonic()

            # Prune oldest entries beyond max window
            max_window = max(self.WINDOWS)
            cutoff_max = now - max_window
            while self._sent_times and self._sent_times[0] < cutoff_max:
                self._sent_times.popleft()
            while self._recv_times and self._recv_times[0] < cutoff_max:
                self._recv_times.popleft()

            result = {
                "sent_total": self._sent_total,
                "recv_total": self._recv_total,
            }

            for w in self.WINDOWS:
                cutoff = now - w
                result[f"sent_{w}s"] = self._count_since(self._sent_times, cutoff)
                result[f"recv_{w}s"] = self._count_since(self._recv_times, cutoff)

            if self._last_recv_time is not None:
                elapsed = now - self._last_recv_time
                result["seconds_since_last_recv"] = round(elapsed, 1)
                import datetime
                wall_offset = time.time() - time.monotonic()
                wall_last = self._last_recv_time + wall_offset
                result["last_recv_datetime"] = datetime.datetime.fromtimestamp(
                    wall_last
                ).strftime("%H:%M:%S")
            else:
                result["seconds_since_last_recv"] = None
                result["last_recv_datetime"] = None

            if self._yellow_threshold_seconds is not None:
                result["yellow_threshold_seconds"] = self._yellow_threshold_seconds

            if self._connections:
                result["connections"] = dict(self._connections)

            if self._gauges:
                result["gauges"] = dict(self._gauges)

            return result

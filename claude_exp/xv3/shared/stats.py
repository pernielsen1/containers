import threading
import time
from collections import deque
from datetime import datetime

WINDOWS = (30, 60, 180, 1800)
_MAX_WINDOW = max(WINDOWS)


class Stats:
    """Thread-safe rolling counters over windows [30, 60, 180, 1800] seconds."""

    def __init__(self, yellow_threshold_seconds=None):
        self._lock = threading.Lock()
        self._yellow_threshold_seconds = yellow_threshold_seconds
        self._sent_total = 0
        self._recv_total = 0
        self._sent_times = deque()
        self._recv_times = deque()
        self._last_recv_monotonic = None
        self._last_recv_datetime = None
        self._connections = {}
        self._gauges = {}

    def set_connection(self, name: str, connected: bool) -> None:
        with self._lock:
            self._connections[name] = connected

    def set_gauge(self, name: str, value) -> None:
        with self._lock:
            self._gauges[name] = value

    def record_sent(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._sent_total += 1
            self._sent_times.append(now)
            self._trim(self._sent_times, now)

    def record_recv(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._recv_total += 1
            self._recv_times.append(now)
            self._trim(self._recv_times, now)
            self._last_recv_monotonic = now
            self._last_recv_datetime = datetime.now()

    @staticmethod
    def _trim(times: deque, now: float) -> None:
        cutoff = now - _MAX_WINDOW
        while times and times[0] < cutoff:
            times.popleft()

    @staticmethod
    def _count_within(times: deque, now: float, window: int) -> int:
        cutoff = now - window
        count = 0
        for t in reversed(times):
            if t < cutoff:
                break
            count += 1
        return count

    def snapshot(self) -> dict:
        now = time.monotonic()
        with self._lock:
            self._trim(self._sent_times, now)
            self._trim(self._recv_times, now)

            result = {
                "sent_total": self._sent_total,
                "recv_total": self._recv_total,
            }
            for window in WINDOWS:
                result[f"sent_{window}s"] = self._count_within(self._sent_times, now, window)
                result[f"recv_{window}s"] = self._count_within(self._recv_times, now, window)

            if self._last_recv_monotonic is not None:
                result["seconds_since_last_recv"] = now - self._last_recv_monotonic
                result["last_recv_datetime"] = self._last_recv_datetime.strftime("%H:%M:%S")
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

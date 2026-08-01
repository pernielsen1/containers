import threading
import time
from collections import deque
from datetime import datetime

_WINDOWS = (30, 60, 180, 1800)


class Stats:
    def __init__(self, yellow_threshold_seconds=None):
        self._lock = threading.Lock()
        self._yellow_threshold_seconds = yellow_threshold_seconds
        self._sent_total = 0
        self._recv_total = 0
        self._sent_times = deque()
        self._recv_times = deque()
        self._last_recv_time = None
        self._connections = {}
        self._gauges = {}

    def set_connection(self, name: str, connected: bool) -> None:
        with self._lock:
            self._connections[name] = bool(connected)

    def set_gauge(self, name: str, value) -> None:
        with self._lock:
            self._gauges[name] = value

    def record_sent(self) -> None:
        with self._lock:
            self._sent_total += 1
            self._sent_times.append(time.time())
            self._trim(self._sent_times)

    def record_recv(self) -> None:
        with self._lock:
            now = time.time()
            self._recv_total += 1
            self._recv_times.append(now)
            self._trim(self._recv_times)
            self._last_recv_time = now

    @staticmethod
    def _trim(times: deque) -> None:
        cutoff = time.time() - max(_WINDOWS)
        while times and times[0] < cutoff:
            times.popleft()

    @staticmethod
    def _count_within(times: deque, window_seconds: int) -> int:
        cutoff = time.time() - window_seconds
        count = 0
        for t in reversed(times):
            if t < cutoff:
                break
            count += 1
        return count

    def snapshot(self) -> dict:
        with self._lock:
            result = {"sent_total": self._sent_total, "recv_total": self._recv_total}
            for window in _WINDOWS:
                result[f"sent_{window}s"] = self._count_within(self._sent_times, window)
                result[f"recv_{window}s"] = self._count_within(self._recv_times, window)

            if self._last_recv_time is not None:
                result["seconds_since_last_recv"] = round(time.time() - self._last_recv_time, 1)
                result["last_recv_datetime"] = datetime.fromtimestamp(self._last_recv_time).strftime("%H:%M:%S")
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

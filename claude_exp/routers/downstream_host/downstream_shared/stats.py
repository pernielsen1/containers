import threading
import time
from collections import deque
from datetime import datetime

_WINDOWS = (30, 60, 180, 1800)

# Bounded by count, not time - unlike _sent_times/_recv_times (which need real timestamps to
# answer "how many in the last 30s"), a percentile only needs *some* recent sample of values, and
# a fixed-size deque keeps memory and the snapshot()-time sort cost bounded even at high TPS
# (sorting a couple thousand floats is sub-millisecond; sorting an unbounded hours-long window
# would not be). Same "keep last N" convention as shared/log_buffer.py's LogBuffer.
_LATENCY_MAXLEN = 2000


def _percentile(sorted_values: list, pct: float) -> float:
    """Linear-interpolation percentile - no numpy dependency for what's otherwise a very small,
    already-dependency-light shared module."""
    if not sorted_values:
        return None
    k = (len(sorted_values) - 1) * pct
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


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
        self._latencies = {}

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

    def record_latency(self, name: str, value_ms: float) -> None:
        """Records one timing sample under a named bucket (e.g. "queue_wait", "crypto_rtt",
        "downstream_rtt", "total" - see router/dispatcher.py) for live per-hop latency
        visibility in /stats, without waiting on an offline soak-test CSV. Available on every
        actor type (Stats is shared), not just the router - any actor with a hop worth timing
        can call this the same way."""
        with self._lock:
            bucket = self._latencies.get(name)
            if bucket is None:
                bucket = deque(maxlen=_LATENCY_MAXLEN)
                self._latencies[name] = bucket
            bucket.append(value_ms)

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

            if self._latencies:
                latency_out = {}
                for name, bucket in self._latencies.items():
                    if not bucket:
                        continue
                    values = sorted(bucket)
                    latency_out[name] = {
                        "count": len(values),
                        "min_ms": round(values[0], 3),
                        "p50_ms": round(_percentile(values, 0.50), 3),
                        "p95_ms": round(_percentile(values, 0.95), 3),
                        "max_ms": round(values[-1], 3),
                    }
                if latency_out:
                    result["latency"] = latency_out

            return result

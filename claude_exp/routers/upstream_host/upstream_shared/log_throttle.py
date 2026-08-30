import logging
import threading


class ThrottledLogger:
    """Wraps a logger for conditions that can fire once per transaction (advice acks, unmatched
    STANs) - at soak TPS these would otherwise flood stdout/the JSON log (every actor inherits
    this process's stdout - see monitor/main.py's Popen call, no per-actor log file) badly
    enough to make a stress run unreadable, per briefs/resilience_v2.md's "this will trigger a
    bunch of 0120 and 0420 messages - interesting if we can keep up" turning into thousands of
    lines/sec once during_kill's retry storm hits.

    Logs the first occurrence of a condition in full, then only every `every`-th repeat after
    that (with the running count appended) - so the condition is never silent, but volume drops
    by ~`every`x. Counts are per `key`, not per call site, so unrelated conditions (e.g. an
    "0420 acked" line vs a "no pending STAN" line) throttle independently."""

    def __init__(self, logger: logging.Logger, every: int = 200):
        self._logger = logger
        self._every = every
        self._counts = {}
        self._lock = threading.Lock()

    def log(self, level: int, key: str, fmt: str, *args) -> None:
        with self._lock:
            count = self._counts[key] = self._counts.get(key, 0) + 1
        if count == 1:
            self._logger.log(level, fmt, *args)
        elif count % self._every == 0:
            self._logger.log(level, fmt + " [occurrence #%d of this condition, throttled]", *args, count)

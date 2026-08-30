import logging
import threading


class ThrottledLogger:
    """Wraps a logger for conditions that can fire once per transaction (crypto_host call
    failures, dropped 0110s) - at soak TPS, plus the deliberate fail-percentage/chaos scenarios
    in briefs/resilience_v2.md, these would otherwise flood stdout badly enough to make a stress
    run unreadable (mirrors upstream_host/upstream_shared/log_throttle.py's own reasoning for
    0120/0420 advice traffic - same flood, this side of the router).

    Logs the first occurrence of a condition in full, then only every `every`-th repeat after
    that (with the running count appended) - so the condition is never silent, but volume drops
    by ~`every`x. Counts are per `key`, not per call site, so unrelated conditions throttle
    independently.

    Diverges from upstream_host's copy by accepting `extra` and passing it through: dispatcher's
    call sites rely on extra={"router_stan": ...} so json_log.py can still join a throttled line
    back to the transaction it belongs to (see _EXTRA_FIELDS)."""

    def __init__(self, logger: logging.Logger, every: int = 200):
        self._logger = logger
        self._every = every
        self._counts = {}
        self._lock = threading.Lock()

    def log(self, level: int, key: str, fmt: str, *args, extra: dict = None) -> None:
        with self._lock:
            count = self._counts[key] = self._counts.get(key, 0) + 1
        if count == 1:
            self._logger.log(level, fmt, *args, extra=extra)
        elif count % self._every == 0:
            self._logger.log(
                level, fmt + " [occurrence #%d of this condition, throttled]", *args, count, extra=extra
            )

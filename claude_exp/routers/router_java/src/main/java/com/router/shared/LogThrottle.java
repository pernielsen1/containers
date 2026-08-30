package com.router.shared;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;
import java.util.logging.Level;
import java.util.logging.Logger;

/** Wraps a Logger for conditions that can fire once per transaction (crypto_host call failures,
 * dropped 0110s) - briefs/resilience_v2.md's fail_percentage/crypto-kill chaos scenarios turn a
 * rare warning into a sustained per-transaction flood without this (mirrors router_py's
 * shared/log_throttle.py::ThrottledLogger 1:1).
 *
 * Logs the first occurrence of a condition in full, then only every `every`-th repeat after that
 * (with the running count appended) - so the condition is never silent, but volume drops by
 * ~`every`x. Counts are per key, not per call site, so unrelated conditions throttle
 * independently. */
public final class LogThrottle {
    private final Logger logger;
    private final int every;
    private final ConcurrentHashMap<String, AtomicLong> counts = new ConcurrentHashMap<>();

    public LogThrottle(Logger logger, int every) {
        this.logger = logger;
        this.every = every;
    }

    public void log(Level level, String key, String message) {
        long count = counts.computeIfAbsent(key, k -> new AtomicLong(0)).incrementAndGet();
        if (count == 1) {
            logger.log(level, message);
        } else if (count % every == 0) {
            logger.log(level, message + " [occurrence #" + count + " of this condition, throttled]");
        }
    }
}

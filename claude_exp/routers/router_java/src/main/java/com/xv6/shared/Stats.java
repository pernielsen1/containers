package com.xv6.shared;

import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Thread-safe rolling counters over windows [30, 60, 180, 1800] seconds. Port of
 * router_py's shared/stats.py.
 */
public final class Stats {

    private static final int[] WINDOWS = {30, 60, 180, 1800};
    private static final DateTimeFormatter TIME_FMT = DateTimeFormatter.ofPattern("HH:mm:ss")
            .withZone(ZoneId.systemDefault());

    private final Object lock = new Object();
    private final Integer yellowThresholdSeconds;
    private long sentTotal = 0;
    private long recvTotal = 0;
    private final Deque<Long> sentTimesMillis = new ArrayDeque<>();
    private final Deque<Long> recvTimesMillis = new ArrayDeque<>();
    private Long lastRecvMillis = null;
    private final Map<String, Boolean> connections = new LinkedHashMap<>();
    private final Map<String, Object> gauges = new LinkedHashMap<>();

    public Stats(Integer yellowThresholdSeconds) {
        this.yellowThresholdSeconds = yellowThresholdSeconds;
    }

    public void setConnection(String name, boolean connected) {
        synchronized (lock) {
            connections.put(name, connected);
        }
    }

    public void setGauge(String name, Object value) {
        synchronized (lock) {
            gauges.put(name, value);
        }
    }

    public void recordSent() {
        synchronized (lock) {
            sentTotal++;
            sentTimesMillis.addLast(System.currentTimeMillis());
            trim(sentTimesMillis);
        }
    }

    public void recordRecv() {
        synchronized (lock) {
            long now = System.currentTimeMillis();
            recvTotal++;
            recvTimesMillis.addLast(now);
            trim(recvTimesMillis);
            lastRecvMillis = now;
        }
    }

    private static void trim(Deque<Long> times) {
        long cutoff = System.currentTimeMillis() - maxWindowMillis();
        while (!times.isEmpty() && times.peekFirst() < cutoff) {
            times.pollFirst();
        }
    }

    private static long maxWindowMillis() {
        int max = 0;
        for (int w : WINDOWS) {
            max = Math.max(max, w);
        }
        return max * 1000L;
    }

    private static int countWithin(Deque<Long> times, int windowSeconds) {
        long cutoff = System.currentTimeMillis() - windowSeconds * 1000L;
        int count = 0;
        for (Long t : times) {
            if (t >= cutoff) {
                count++;
            }
        }
        return count;
    }

    public Map<String, Object> snapshot() {
        synchronized (lock) {
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("sent_total", sentTotal);
            result.put("recv_total", recvTotal);
            for (int window : WINDOWS) {
                result.put("sent_" + window + "s", countWithin(sentTimesMillis, window));
                result.put("recv_" + window + "s", countWithin(recvTimesMillis, window));
            }

            if (lastRecvMillis != null) {
                double secondsSince = (System.currentTimeMillis() - lastRecvMillis) / 1000.0;
                result.put("seconds_since_last_recv", Math.round(secondsSince * 10) / 10.0);
                result.put("last_recv_datetime", TIME_FMT.format(Instant.ofEpochMilli(lastRecvMillis)));
            } else {
                result.put("seconds_since_last_recv", null);
                result.put("last_recv_datetime", null);
            }

            if (yellowThresholdSeconds != null) {
                result.put("yellow_threshold_seconds", yellowThresholdSeconds);
            }

            if (!connections.isEmpty()) {
                result.put("connections", new LinkedHashMap<>(connections));
            }

            if (!gauges.isEmpty()) {
                result.put("gauges", new LinkedHashMap<>(gauges));
            }

            return result;
        }
    }
}

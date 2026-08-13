package com.router.shared;

import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Deque;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Thread-safe rolling counters over windows [30, 60, 180, 1800] seconds. Port of
 * router_py's shared/stats.py.
 */
public final class Stats {

    private static final int[] WINDOWS = {30, 60, 180, 1800};
    private static final DateTimeFormatter TIME_FMT = DateTimeFormatter.ofPattern("HH:mm:ss")
            .withZone(ZoneId.systemDefault());
    // Bounded by count, not time - a percentile only needs *some* recent sample of values, and a
    // fixed-size deque keeps memory and the snapshot()-time sort cost bounded even at high TPS.
    // Same "keep last N" convention as LogBuffer. Matches router_py's shared/stats.py.
    private static final int LATENCY_MAXLEN = 2000;

    private final Object lock = new Object();
    private final Integer yellowThresholdSeconds;
    private long sentTotal = 0;
    private long recvTotal = 0;
    private final Deque<Long> sentTimesMillis = new ArrayDeque<>();
    private final Deque<Long> recvTimesMillis = new ArrayDeque<>();
    private Long lastRecvMillis = null;
    private final Map<String, Boolean> connections = new LinkedHashMap<>();
    private final Map<String, Object> gauges = new LinkedHashMap<>();
    private final Map<String, Deque<Double>> latencies = new LinkedHashMap<>();

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

    /**
     * Records one timing sample under a named bucket (e.g. "queue_wait", "crypto_rtt",
     * "downstream_rtt", "total" - see Dispatcher) for live per-hop latency visibility in
     * /stats, without waiting on an offline soak-test CSV. Available on every actor type
     * (Stats is shared), not just the router - any actor with a hop worth timing can call
     * this the same way.
     */
    public void recordLatency(String name, double valueMs) {
        synchronized (lock) {
            Deque<Double> bucket = latencies.computeIfAbsent(name, k -> new ArrayDeque<>());
            bucket.addLast(valueMs);
            while (bucket.size() > LATENCY_MAXLEN) {
                bucket.pollFirst();
            }
        }
    }

    /** Linear-interpolation percentile - matches router_py's _percentile helper. */
    private static double percentile(List<Double> sortedValues, double pct) {
        double k = (sortedValues.size() - 1) * pct;
        int f = (int) k;
        int c = Math.min(f + 1, sortedValues.size() - 1);
        if (f == c) {
            return sortedValues.get(f);
        }
        return sortedValues.get(f) + (sortedValues.get(c) - sortedValues.get(f)) * (k - f);
    }

    private static double round3(double v) {
        return Math.round(v * 1000.0) / 1000.0;
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

            if (!latencies.isEmpty()) {
                Map<String, Object> latencyOut = new LinkedHashMap<>();
                for (Map.Entry<String, Deque<Double>> e : latencies.entrySet()) {
                    if (e.getValue().isEmpty()) {
                        continue;
                    }
                    List<Double> values = new ArrayList<>(e.getValue());
                    Collections.sort(values);
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("count", values.size());
                    row.put("min_ms", round3(values.get(0)));
                    row.put("p50_ms", round3(percentile(values, 0.50)));
                    row.put("p95_ms", round3(percentile(values, 0.95)));
                    row.put("max_ms", round3(values.get(values.size() - 1)));
                    latencyOut.put(e.getKey(), row);
                }
                if (!latencyOut.isEmpty()) {
                    result.put("latency", latencyOut);
                }
            }

            return result;
        }
    }
}

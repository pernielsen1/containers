package com.router.shared;

import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Port of router_py's tests/test_stats.py. */
class StatsTest {

    @Test
    void countersAndWindows() {
        Stats s = new Stats(5);
        for (int i = 0; i < 3; i++) {
            s.recordSent();
        }
        for (int i = 0; i < 2; i++) {
            s.recordRecv();
        }

        Map<String, Object> snap = s.snapshot();
        assertEquals(3L, snap.get("sent_total"));
        assertEquals(2L, snap.get("recv_total"));
        for (int window : new int[]{30, 60, 180, 1800}) {
            assertEquals(3, snap.get("sent_" + window + "s"));
            assertEquals(2, snap.get("recv_" + window + "s"));
        }
        assertNotNull(snap.get("last_recv_datetime"));
        assertNotNull(snap.get("seconds_since_last_recv"));
        assertTrue((double) snap.get("seconds_since_last_recv") < 1);
        assertEquals(5, snap.get("yellow_threshold_seconds"));
    }

    @Test
    void connectionsAndGauges() {
        Stats s = new Stats(null);
        s.setConnection("upstream", true);
        s.setGauge("queue_depth", 4);
        Map<String, Object> snap = s.snapshot();
        assertEquals(Map.of("upstream", true), snap.get("connections"));
        assertEquals(Map.of("queue_depth", 4), snap.get("gauges"));
    }

    @Test
    void noRecvYetAndNoOptionalKeys() {
        Stats s = new Stats(null);
        Map<String, Object> snap = s.snapshot();
        assertNull(snap.get("seconds_since_last_recv"));
        assertNull(snap.get("last_recv_datetime"));
        assertFalse(snap.containsKey("yellow_threshold_seconds"));
        assertFalse(snap.containsKey("connections"));
        assertFalse(snap.containsKey("gauges"));
    }

    @SuppressWarnings("unchecked")
    @Test
    void latencyPercentiles() {
        Stats s = new Stats(null);
        // 1..100 ms so percentiles are easy to reason about
        for (int v = 1; v <= 100; v++) {
            s.recordLatency("downstream_rtt", v);
        }

        Map<String, Object> snap = s.snapshot();
        Map<String, Object> bucket = ((Map<String, Map<String, Object>>) snap.get("latency")).get("downstream_rtt");
        assertEquals(100, bucket.get("count"));
        assertEquals(1.0, bucket.get("min_ms"));
        assertEquals(100.0, bucket.get("max_ms"));
        double p50 = (double) bucket.get("p50_ms");
        double p95 = (double) bucket.get("p95_ms");
        assertTrue(49 <= p50 && p50 <= 51);
        assertTrue(94 <= p95 && p95 <= 96);
    }

    @SuppressWarnings("unchecked")
    @Test
    void latencyBucketsAreIndependent() {
        Stats s = new Stats(null);
        s.recordLatency("queue_wait", 1.0);
        s.recordLatency("crypto_rtt", 5.0);
        Map<String, Object> snap = s.snapshot();
        Map<String, Map<String, Object>> latency = (Map<String, Map<String, Object>>) snap.get("latency");
        assertEquals(Map.of("queue_wait", "x", "crypto_rtt", "x").keySet(), latency.keySet());
        assertEquals(1, latency.get("queue_wait").get("count"));
        assertEquals(1, latency.get("crypto_rtt").get("count"));
    }

    @SuppressWarnings("unchecked")
    @Test
    void latencyBucketBoundedByCount() {
        Stats s = new Stats(null);
        for (int v = 0; v < 3000; v++) {
            s.recordLatency("total", v);
        }
        Map<String, Object> snap = s.snapshot();
        Map<String, Object> bucket = ((Map<String, Map<String, Object>>) snap.get("latency")).get("total");
        // only the most recent LATENCY_MAXLEN (2000) samples are kept
        assertEquals(2000, bucket.get("count"));
        assertEquals(1000.0, bucket.get("min_ms"));
        assertEquals(2999.0, bucket.get("max_ms"));
    }
}

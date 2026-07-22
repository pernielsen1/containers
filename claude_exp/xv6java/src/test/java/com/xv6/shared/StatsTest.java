package com.xv6.shared;

import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Port of xv5's tests/test_stats.py. */
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
}

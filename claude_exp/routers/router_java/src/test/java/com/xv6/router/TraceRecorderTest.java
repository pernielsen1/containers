package com.xv6.router;

import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Port of router_py's tests/test_trace.py. */
class TraceRecorderTest {

    @Test
    void disarmedByDefault() {
        TraceRecorder trace = new TraceRecorder();
        assertFalse(trace.start("000001", "100001", "4111111111111111", "0100", new byte[]{0x01, 0x02}));

        Map<String, Object> snapshot = trace.snapshot();
        assertEquals(false, snapshot.get("armed"));
        assertEquals(0, snapshot.get("remaining"));
        assertTrue(((List<?>) snapshot.get("entries")).isEmpty());
    }

    @Test
    void armCapturesAndAutoDisarmsAfterCount() {
        TraceRecorder trace = new TraceRecorder();
        trace.arm(1, null, null);

        boolean started = trace.start("000001", "100001", "4111111111111111", "0100", new byte[]{(byte) 0xde, (byte) 0xad});
        assertTrue(started);
        assertEquals(false, trace.snapshot().get("armed"));  // count exhausted

        // a second transaction shouldn't be captured now that the count is used up
        assertFalse(trace.start("000002", "100002", "4111111111111111", "0100", new byte[]{(byte) 0xbe, (byte) 0xef}));
    }

    @SuppressWarnings("unchecked")
    @Test
    void hopAndFinishBuildFullEntry() {
        TraceRecorder trace = new TraceRecorder();
        trace.arm(1, null, null);
        trace.start("000001", "100001", "4111111111111111", "0100", new byte[]{0x01, 0x02});

        Map<String, Object> cryptoExtra = new LinkedHashMap<>();
        cryptoExtra.put("crypto_ms", 1.5);
        cryptoExtra.put("enriched", true);
        trace.hop("000001", "crypto_call", null, cryptoExtra);
        trace.hop("000001", "downstream_send", new byte[]{0x03, 0x04});
        trace.finish("000001");

        Map<String, Object> snap = trace.snapshot();
        List<Map<String, Object>> entries = (List<Map<String, Object>>) snap.get("entries");
        assertFalse(entries.isEmpty(), "finished trace should appear in snapshot entries");
        Map<String, Object> entry = entries.get(0);
        assertEquals("000001", entry.get("router_stan"));
        assertEquals("100001", entry.get("upstream_stan"));
        assertEquals("4111111111111111", entry.get("pan"));

        List<Map<String, Object>> hops = (List<Map<String, Object>>) entry.get("hops");
        assertEquals(List.of("upstream_recv", "crypto_call", "downstream_send"),
                hops.stream().map(h -> h.get("stage")).toList());
        assertEquals("0102", hops.get(0).get("wire_hex"));
        assertEquals("0304", hops.get(2).get("wire_hex"));
        assertEquals(1.5, hops.get(1).get("crypto_ms"));
        assertFalse(entry.containsKey("_started_at_nanos"));
    }

    @Test
    void hopOnUntrackedStanIsANoop() {
        TraceRecorder trace = new TraceRecorder();
        trace.arm(5, null, null);
        // never called start() for this stan - simulates a transaction that wasn't selected by arm()
        trace.hop("999999", "downstream_recv", new byte[]{0x00});
        assertTrue(((List<?>) trace.snapshot().get("entries")).isEmpty());
    }

    @Test
    void filterByUpstreamStan() {
        TraceRecorder trace = new TraceRecorder();
        trace.arm(5, "100002", null);
        assertFalse(trace.start("000001", "100001", "4111111111111111", "0100", new byte[0]));
        assertTrue(trace.start("000002", "100002", "4111111111111111", "0100", new byte[0]));
    }

    @Test
    void filterByPan() {
        TraceRecorder trace = new TraceRecorder();
        trace.arm(5, null, "4222222222222222");
        assertFalse(trace.start("000001", "100001", "4111111111111111", "0100", new byte[0]));
        assertTrue(trace.start("000002", "100002", "4222222222222222", "0100", new byte[0]));
    }

    @SuppressWarnings("unchecked")
    @Test
    void abandonInProgressMarksIncompleteAndClears() {
        TraceRecorder trace = new TraceRecorder();
        trace.arm(1, null, null);
        trace.start("000001", "100001", "4111111111111111", "0100", new byte[]{0x01});

        List<Map<String, Object>> abandoned = trace.abandonInProgress();
        assertEquals(1, abandoned.size());
        assertEquals(true, abandoned.get(0).get("incomplete"));

        Map<String, Object> snap = trace.snapshot();
        List<Map<String, Object>> entries = (List<Map<String, Object>>) snap.get("entries");
        assertEquals(1, entries.size());
        assertEquals(true, entries.get(0).get("incomplete"));

        // in-progress table is cleared - a late hop() call for this stan is now a no-op
        trace.hop("000001", "downstream_recv", null);
        assertEquals(1, ((List<?>) trace.snapshot().get("entries")).size());
    }

    @Test
    void rearmingClearsPreviousFilters() {
        TraceRecorder trace = new TraceRecorder();
        trace.arm(1, "100001", null);
        trace.arm(3, null, null);  // re-arm without a filter
        assertTrue(trace.start("000001", "999999", "4111111111111111", "0100", new byte[0]));
    }
}

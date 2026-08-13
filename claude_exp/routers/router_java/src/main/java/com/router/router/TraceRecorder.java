package com.router.router;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * On-demand, self-expiring capture of full per-hop transaction detail for live diagnosis at
 * production volume - briefs/debug_trace_master.md Phase 4. Off by default: the hot path pays
 * only a lock + map-lookup per hop call site when disarmed (no wire-byte hex-encoding, no extra
 * allocation), so it's safe to leave wired in permanently rather than only under a feature flag.
 * Once armed via arm(), captures the next {@code count} transactions - optionally filtered to a
 * specific upstream_stan or pan - end to end: raw wire bytes at every hop plus per-hop elapsed
 * time, then auto-disarms so a capture can never accidentally run forever. Port of router_py's
 * router/trace.py.
 */
public final class TraceRecorder {

    private final Object lock = new Object();
    private final int maxEntries;

    private boolean armed;
    private int remaining;
    private String filterStan;
    private String filterPan;
    private final Deque<Map<String, Object>> entries = new ArrayDeque<>();
    private final Map<String, Map<String, Object>> inProgress = new LinkedHashMap<>();

    public TraceRecorder() {
        this(50);
    }

    public TraceRecorder(int maxEntries) {
        this.maxEntries = maxEntries;
    }

    public void arm(int count, String stan, String pan) {
        synchronized (lock) {
            remaining = Math.max(count, 0);
            armed = remaining > 0;
            filterStan = (stan == null || stan.isEmpty()) ? null : stan;
            filterPan = (pan == null || pan.isEmpty()) ? null : pan;
        }
    }

    /**
     * Called once per transaction, at its first hop. Returns whether this transaction is being
     * traced, so callers can skip building later hop details (e.g. re-encoding bytes that would
     * otherwise just be discarded) when it isn't.
     */
    public boolean start(String routerStan, String upstreamStan, String pan, String mti, byte[] raw) {
        if (!armed) {
            return false;
        }
        synchronized (lock) {
            if (!armed) {
                return false;
            }
            if (filterStan != null && !filterStan.equals(upstreamStan)) {
                return false;
            }
            if (filterPan != null && !filterPan.equals(pan)) {
                return false;
            }
            remaining -= 1;
            if (remaining <= 0) {
                armed = false;
            }

            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("router_stan", routerStan);
            entry.put("upstream_stan", upstreamStan);
            entry.put("pan", pan);
            entry.put("mti", mti);
            entry.put("_started_at_nanos", System.nanoTime());

            List<Map<String, Object>> hops = new ArrayList<>();
            Map<String, Object> firstHop = new LinkedHashMap<>();
            firstHop.put("stage", "upstream_recv");
            firstHop.put("elapsed_ms", 0.0);
            firstHop.put("wire_hex", toHex(raw));
            hops.add(firstHop);
            entry.put("hops", hops);

            inProgress.put(routerStan, entry);
            return true;
        }
    }

    public boolean isTracing(String routerStan) {
        synchronized (lock) {
            return inProgress.containsKey(routerStan);
        }
    }

    public void hop(String routerStan, String stage, byte[] raw) {
        hop(routerStan, stage, raw, null);
    }

    @SuppressWarnings("unchecked")
    public void hop(String routerStan, String stage, byte[] raw, Map<String, Object> extraFields) {
        synchronized (lock) {
            Map<String, Object> entry = inProgress.get(routerStan);
            if (entry == null) {
                return;
            }
            long startedAtNanos = (long) entry.get("_started_at_nanos");
            double elapsedMs = (System.nanoTime() - startedAtNanos) / 1_000_000.0;

            Map<String, Object> record = new LinkedHashMap<>();
            record.put("stage", stage);
            record.put("elapsed_ms", round3(elapsedMs));
            if (raw != null) {
                record.put("wire_hex", toHex(raw));
            }
            if (extraFields != null) {
                record.putAll(extraFields);
            }
            ((List<Map<String, Object>>) entry.get("hops")).add(record);
        }
    }

    public void finish(String routerStan) {
        synchronized (lock) {
            Map<String, Object> entry = inProgress.remove(routerStan);
            if (entry != null) {
                entry.remove("_started_at_nanos");
                addEntry(entry);
            }
        }
    }

    /**
     * Flushes any traces that were mid-capture into entries (marked incomplete) instead of
     * leaking them silently - called from Dispatcher.drainAndStop() so a session teardown
     * mid-trace doesn't just vanish, same reasoning as the pending-transaction abandonment log
     * added there.
     */
    public List<Map<String, Object>> abandonInProgress() {
        synchronized (lock) {
            List<Map<String, Object>> abandoned = new ArrayList<>(inProgress.values());
            for (Map<String, Object> entry : abandoned) {
                entry.put("incomplete", true);
                entry.remove("_started_at_nanos");
                addEntry(entry);
            }
            inProgress.clear();
            return abandoned;
        }
    }

    public Map<String, Object> snapshot() {
        synchronized (lock) {
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("armed", armed);
            result.put("remaining", remaining);
            result.put("entries", new ArrayList<>(entries));
            return result;
        }
    }

    private void addEntry(Map<String, Object> entry) {
        entries.addLast(entry);
        while (entries.size() > maxEntries) {
            entries.pollFirst();
        }
    }

    private static double round3(double v) {
        return Math.round(v * 1000.0) / 1000.0;
    }

    private static String toHex(byte[] raw) {
        return raw == null ? "" : HexFormat.of().formatHex(raw);
    }
}

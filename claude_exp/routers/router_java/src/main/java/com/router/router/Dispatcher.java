package com.router.router;

import com.solab.iso8583.IsoMessage;
import com.solab.iso8583.MessageFactory;
import com.router.shared.ImsConnect;
import com.router.shared.IsoUtils;
import com.router.shared.LogThrottle;
import com.router.shared.Stats;
import com.router.shared.StopEvent;

import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * Worker pool. Routes 0100 upstream -> crypto -> downstream. Routes 0110/0130/0430 downstream ->
 * upstream (STAN lookup). Port of router_py's router/dispatcher.py.
 *
 * Concurrency mapping (see briefs/java_container_router.md): {@code queue.Queue(maxsize=N)} ->
 * {@link ArrayBlockingQueue}; {@code dict + threading.Lock} for the pending-STAN map ->
 * {@link ConcurrentHashMap}; {@code threading.Thread} x worker_threads -> plain daemon
 * {@link Thread}s (a fixed-size pool, matching the Python "not thread-per-message" design note).
 */
public final class Dispatcher {

    private static final Logger logger = Logger.getLogger(Dispatcher.class.getName());
    private static final LogThrottle throttledLog = new LogThrottle(logger, 200);
    private static final int STAN_MODULUS = 1_000_000;
    private static final Set<String> RESPONSE_MTIS = Set.of("0110", "0130", "0430");
    private static final RoutedMessage POISON = new RoutedMessage(null, null, null, null);
    private static final ResponseItem RESPONSE_POISON = new ResponseItem(null, null);

    /** (resp, raw) pair - raw is threaded through so TraceRecorder can capture the
     * downstream_recv hop's wire bytes, same as router_py's response_queue tuple. */
    private record ResponseItem(Map<String, String> resp, byte[] raw) {
    }

    private final RouterConfig cfg;
    private final DownstreamConnection downstream;
    private final CryptoClient crypto;
    private final MessageFactory<IsoMessage> factory;
    // See RouterSession.upstreamFactory - same upstream-vs-downstream leg split.
    private final MessageFactory<IsoMessage> upstreamFactory;
    private final Stats stats;
    private final StopEvent reconnectEvent;
    private final TraceRecorder trace = new TraceRecorder();

    private final BlockingQueue<RoutedMessage> queue;
    private final BlockingQueue<ResponseItem> responseQueue;
    private final Map<String, PendingEntry> pending = new ConcurrentHashMap<>();
    private final Object stanLock = new Object();
    private int stanCounter = 0;
    private final StopEvent stopEvent = new StopEvent();
    private final List<Thread> workerThreads = new ArrayList<>();
    private final List<Thread> responseWorkerThreads = new ArrayList<>();
    private Thread reaperThread;

    public Dispatcher(RouterConfig cfg, DownstreamConnection downstream, CryptoClient crypto,
            MessageFactory<IsoMessage> factory, Stats stats, StopEvent reconnectEvent) {
        this(cfg, downstream, crypto, factory, stats, reconnectEvent, factory);
    }

    public Dispatcher(RouterConfig cfg, DownstreamConnection downstream, CryptoClient crypto,
            MessageFactory<IsoMessage> factory, Stats stats, StopEvent reconnectEvent,
            MessageFactory<IsoMessage> upstreamFactory) {
        this.cfg = cfg;
        this.downstream = downstream;
        this.crypto = crypto;
        this.factory = factory;
        this.upstreamFactory = upstreamFactory;
        this.stats = stats;
        this.reconnectEvent = reconnectEvent;
        this.queue = new ArrayBlockingQueue<>(cfg.queueMaxsize());
        this.responseQueue = new ArrayBlockingQueue<>(cfg.queueMaxsize());
    }

    /** Exposed for the /trace route (RouterMain) - mirrors router_py's public `dispatcher.trace`. */
    public TraceRecorder trace() {
        return trace;
    }

    private String nextStan() {
        synchronized (stanLock) {
            stanCounter = (stanCounter + 1) % STAN_MODULUS;
            return String.format("%06d", stanCounter);
        }
    }

    public void start() {
        // Blocks until every worker/response-worker thread has completed its own
        // crypto.warmup() (see CryptoClient's warmupGate doc) before start() returns. Previously
        // start() returned immediately, so early-finishing threads could already be sending real
        // traffic through their now-hot client while other threads were still mid warmup-gate
        // queue doing their own first-ever TLS handshake - two genuinely independent HttpClients,
        // but concurrent all the same, which is exactly the java.net.http.HttpClient bug
        // warmupGate exists to avoid ("fatal alert: internal_error", reproduced against this
        // router's own soak run: a burst of ~9 failures ~30s after startup, breaker never fully
        // recovering). Making start() wait here closes that gap at the cost of delaying
        // upstream-accept readiness by roughly (workerThreads + responseWorkerThreads) * the
        // per-thread warmup cost - see stress_run.sh's correspondingly longer /start retry
        // window.
        CountDownLatch warmupLatch = new CountDownLatch(cfg.workerThreads() + cfg.responseWorkerThreads());
        for (int i = 0; i < cfg.workerThreads(); i++) {
            Thread t = new Thread(() -> workerLoop(warmupLatch), "worker-" + i);
            t.setDaemon(true);
            t.start();
            workerThreads.add(t);
        }
        for (int i = 0; i < cfg.responseWorkerThreads(); i++) {
            Thread t = new Thread(() -> responseWorkerLoop(warmupLatch), "response-worker-" + i);
            t.setDaemon(true);
            t.start();
            responseWorkerThreads.add(t);
        }
        reaperThread = new Thread(this::pendingReaper, "pending-reaper");
        reaperThread.setDaemon(true);
        reaperThread.start();
        try {
            warmupLatch.await();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    /** Blocking enqueue (backpressure). */
    public void submit(RoutedMessage msg) throws InterruptedException {
        RoutedMessage timed = msg.withEnqueuedAt(System.nanoTime());
        queue.put(timed);
        stats.setGauge("queue_depth", queue.size());
        logger.fine("dispatcher: queued mti=" + msg.req().get("t") + " (queue_depth=" + queue.size() + ")");
    }

    /**
     * Enqueues a downstream response (0110/0130/0430) for handling by the response worker pool,
     * instead of processing it inline on the caller's thread. Keeps the 0110 leg's crypto call
     * (validate_0110) from being a single-threaded bottleneck that's entirely separate from - and
     * doesn't have to compete with - the 0100 leg's queue.
     */
    public void submitResponse(Map<String, String> resp, byte[] raw) throws InterruptedException {
        responseQueue.put(new ResponseItem(resp, raw));
        stats.setGauge("response_queue_depth", responseQueue.size());
        logger.fine("dispatcher: queued response mti=" + resp.get("t")
                + " (response_queue_depth=" + responseQueue.size() + ")");
    }

    private void workerLoop(CountDownLatch warmupLatch) {
        crypto.warmup();
        warmupLatch.countDown();
        while (true) {
            RoutedMessage msg;
            try {
                msg = queue.take();
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            }
            stats.setGauge("queue_depth", queue.size());
            if (msg == POISON) {
                return;
            }
            if (msg.enqueuedAtNanos() != 0) {
                stats.recordLatency("queue_wait", (System.nanoTime() - msg.enqueuedAtNanos()) / 1_000_000.0);
            }
            try {
                process(msg);
            } catch (IOException e) {
                logger.warning("downstream send failed while dispatching; triggering reconnect");
                reconnectEvent.set();
            } catch (Exception e) {
                logger.log(Level.SEVERE, "unexpected error processing dispatched message", e);
            }
        }
    }

    private void responseWorkerLoop(CountDownLatch warmupLatch) {
        crypto.warmup();
        warmupLatch.countDown();
        while (true) {
            ResponseItem item;
            try {
                item = responseQueue.take();
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            }
            stats.setGauge("response_queue_depth", responseQueue.size());
            if (item == RESPONSE_POISON) {
                return;
            }
            try {
                handleResponse(item.resp(), item.raw());
            } catch (Exception e) {
                logger.log(Level.SEVERE, "unexpected error processing dispatched response", e);
            }
        }
    }

    private void process(RoutedMessage msg) throws IOException {
        Map<String, String> req = msg.req();
        String mti = req.get("t");
        String pan = req.getOrDefault("2", "");
        String upstreamStan = req.getOrDefault("11", "");

        String routerStan = nextStan();
        boolean tracing = trace.start(routerStan, upstreamStan, pan, mti, msg.raw());

        Map<String, String> fwd = new LinkedHashMap<>(req);
        if ("0100".equals(mti)) {
            long cryptoStart = System.nanoTime();
            String result = crypto.validate("validate_0100", pan, req.getOrDefault("47", ""), routerStan);
            double cryptoMs = (System.nanoTime() - cryptoStart) / 1_000_000.0;
            stats.recordLatency("crypto_rtt", cryptoMs);
            if (tracing) {
                Map<String, Object> extra = new LinkedHashMap<>();
                extra.put("crypto_ms", Math.round(cryptoMs * 1000.0) / 1000.0);
                extra.put("enriched", result != null && !result.isEmpty());
                trace.hop(routerStan, "crypto_call", null, extra);
            }
            // briefs/resilience_v2.md: crypto_host is allowed to fail open on the request leg -
            // both a genuine failure (null) and a legitimate no-op ("") mean "don't overwrite f47".
            if (result != null && !result.isEmpty()) {
                fwd.put("47", result);
            }
        }
        fwd.put("11", routerStan);

        // `factory` (downstream leg), not `upstreamFactory`, even though `fwd` originated
        // upstream - this frame goes out over `downstream.send` below.
        byte[] encoded = IsoUtils.fromMap(factory, fwd).writeData();
        if (tracing) {
            trace.hop(routerStan, "downstream_send", encoded);
        }

        long startedAtNanos = msg.enqueuedAtNanos() != 0 ? msg.enqueuedAtNanos() : System.nanoTime();
        PendingEntry entry = new PendingEntry(
                msg.upConn(), msg.upWriteLock(), upstreamStan, System.nanoTime(), startedAtNanos);
        if (pending.putIfAbsent(routerStan, entry) != null) {
            logger.severe("router_stan " + routerStan + " still outstanding; overwriting pending entry");
            pending.put(routerStan, entry);
        }
        stats.setGauge("pending_count", pending.size());

        byte[] frame = ImsConnect.buildFrame(
                0x00, cfg.downstream().irmId(), cfg.downstream().clientId(), fwd.get("t"), encoded, null);
        downstream.send(frame);
        stats.recordSent();
        logger.fine("dispatcher: forwarded mti=" + mti + " to downstream, upstream_stan=" + upstreamStan
                + " router_stan=" + routerStan);
    }

    /** Called from a response-worker thread (or directly by tests). */
    public void handleResponse(Map<String, String> resp, byte[] raw) {
        String mti = resp.get("t");
        if ("0810".equals(mti)) {
            return;
        }
        if (!RESPONSE_MTIS.contains(mti)) {
            logger.warning("unexpected response MTI from downstream: " + mti);
            return;
        }

        String routerStan = resp.getOrDefault("11", "");
        trace.hop(routerStan, "downstream_recv", raw);
        boolean tracing = trace.isTracing(routerStan);

        long now = System.nanoTime();
        PendingEntry entry = pending.remove(routerStan);
        stats.setGauge("pending_count", pending.size());
        if (entry == null) {
            logger.warning("no pending entry for router_stan " + routerStan);
            if (tracing) {
                trace.finish(routerStan);
            }
            return;
        }
        stats.recordLatency("downstream_rtt", (now - entry.createdAtNanos()) / 1_000_000.0);

        Map<String, String> fwd = new LinkedHashMap<>(resp);
        fwd.put("11", entry.upstreamStan());
        if ("0110".equals(mti)) {
            String pan = resp.getOrDefault("2", "");
            long cryptoStart = System.nanoTime();
            String result = crypto.validate("validate_0110", pan, resp.getOrDefault("47", ""), routerStan);
            double cryptoMs = (System.nanoTime() - cryptoStart) / 1_000_000.0;
            stats.recordLatency("crypto_rtt", cryptoMs);
            if (tracing) {
                Map<String, Object> extra = new LinkedHashMap<>();
                extra.put("crypto_ms", Math.round(cryptoMs * 1000.0) / 1000.0);
                extra.put("enriched", result != null && !result.isEmpty());
                trace.hop(routerStan, "crypto_call", null, extra);
            }
            if (result == null) {
                // briefs/resilience_v2.md: crypto_host is allowed to fail open on the request leg
                // (above), but a genuine failure here on the response leg means the cardholder's
                // decision was never validated - drop the 0110 rather than forward it unvalidated.
                // Upstream never gets a reply, times out on its own advice_timeout_seconds, and
                // falls back to 0420/0120 store-and-forward - the whole point of the
                // crypto_host-kill chaos scenario.
                throttledLog.log(Level.WARNING, "validate_0110_failed",
                        "validate_0110 failed for router_stan " + routerStan
                                + " - dropping response, upstream will time out and fall back to advice/reversal");
                if (tracing) {
                    trace.finish(routerStan);
                }
                return;
            }
            if (!result.isEmpty()) {
                fwd.put("47", result);
            }
        }

        byte[] encoded = IsoUtils.fromMap(upstreamFactory, fwd).writeData();
        if (tracing) {
            trace.hop(routerStan, "upstream_send", encoded);
        }
        try {
            entry.upWriteLock().lock();
            try {
                Upstream.writeUpstream(entry.upConn(), encoded, cfg.upstream());
            } finally {
                entry.upWriteLock().unlock();
            }
            stats.recordSent();
            logger.fine("dispatcher: forwarded mti=" + mti + " to upstream, router_stan=" + routerStan
                    + " upstream_stan=" + entry.upstreamStan());
        } catch (IOException e) {
            // entry.upConn() can be closed by session teardown racing this write.
            logger.warning("failed to write response upstream for stan " + entry.upstreamStan());
        }
        stats.recordLatency("total", (System.nanoTime() - entry.startedAtNanos()) / 1_000_000.0);
        if (tracing) {
            trace.finish(routerStan);
        }
    }

    private void pendingReaper() {
        try {
            while (!stopEvent.waitFor(1, TimeUnit.SECONDS)) {
                long now = System.nanoTime();
                long ttlNanos = cfg.pendingTtlSeconds() * 1_000_000_000L;
                List<Map.Entry<String, PendingEntry>> expired = new ArrayList<>();
                for (Map.Entry<String, PendingEntry> e : pending.entrySet()) {
                    if ((now - e.getValue().createdAtNanos()) > ttlNanos) {
                        expired.add(e);
                    }
                }
                for (Map.Entry<String, PendingEntry> e : expired) {
                    pending.remove(e.getKey(), e.getValue());
                }
                if (!expired.isEmpty()) {
                    stats.setGauge("pending_count", pending.size());
                }

                for (Map.Entry<String, PendingEntry> e : expired) {
                    String stan = e.getKey();
                    PendingEntry entry = e.getValue();
                    logger.warning("pending entry " + stan + " expired after " + cfg.pendingTtlSeconds()
                            + "s; sending local decline");
                    Map<String, String> decline = new LinkedHashMap<>();
                    decline.put("t", "0110");
                    decline.put("11", entry.upstreamStan());
                    decline.put("39", "91");
                    try {
                        byte[] encoded = IsoUtils.fromMap(upstreamFactory, decline).writeData();
                        entry.upWriteLock().lock();
                        try {
                            Upstream.writeUpstream(entry.upConn(), encoded, cfg.upstream());
                        } finally {
                            entry.upWriteLock().unlock();
                        }
                        stats.recordSent();
                    } catch (IOException ex) {
                        logger.warning("failed to write expiry decline for stan " + entry.upstreamStan());
                    }
                }
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    /**
     * Read-only view of in-flight transactions (downstream request sent, no response yet) for
     * live diagnosis - e.g. "why is this router stuck", without waiting for the pendingTtlSeconds
     * reaper to expire and decline them. Sorted oldest-first so a stuck transaction sorts to the
     * top. Port of router_py's Dispatcher.pending_snapshot().
     */
    public List<Map<String, Object>> pendingSnapshot() {
        long now = System.nanoTime();
        List<Map<String, Object>> entries = new ArrayList<>();
        for (Map.Entry<String, PendingEntry> e : pending.entrySet()) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("router_stan", e.getKey());
            row.put("upstream_stan", e.getValue().upstreamStan());
            double ageSeconds = (now - e.getValue().createdAtNanos()) / 1_000_000_000.0;
            row.put("age_seconds", Math.round(ageSeconds * 1000.0) / 1000.0);
            entries.add(row);
        }
        entries.sort((a, b) -> Double.compare((double) b.get("age_seconds"), (double) a.get("age_seconds")));
        return entries;
    }

    /** Operator drain; returns dropped counts. */
    public Map<String, Integer> purge() {
        int droppedQueue = 0;
        while (queue.poll() != null) {
            droppedQueue++;
        }
        int droppedResponseQueue = 0;
        while (responseQueue.poll() != null) {
            droppedResponseQueue++;
        }
        int droppedPending = pending.size();
        pending.clear();
        stats.setGauge("queue_depth", queue.size());
        stats.setGauge("response_queue_depth", responseQueue.size());
        stats.setGauge("pending_count", 0);

        Map<String, Integer> result = new LinkedHashMap<>();
        result.put("dropped_queue", droppedQueue);
        result.put("dropped_response_queue", droppedResponseQueue);
        result.put("dropped_pending", droppedPending);
        return result;
    }

    /** None sentinels + join (session teardown). */
    public void drainAndStop() {
        stopEvent.set();
        for (int i = 0; i < workerThreads.size(); i++) {
            try {
                queue.put(POISON);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
        for (int i = 0; i < responseWorkerThreads.size(); i++) {
            try {
                responseQueue.put(RESPONSE_POISON);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
        for (Thread t : workerThreads) {
            try {
                t.join(5000);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
        for (Thread t : responseWorkerThreads) {
            try {
                t.join(5000);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
        if (reaperThread != null) {
            try {
                reaperThread.join(5000);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }

        // Session teardown (upstream or downstream disconnect, reconnect) previously discarded
        // any still-in-flight transactions with zero trace - unlike purge(), which reports
        // dropped_pending, this path left no log line explaining why a transaction just
        // vanished. There's nothing to *do* about them (the upstream client that would receive
        // a decline is already gone), but a live-diagnosis session needs the record. Safe to
        // read/clear `pending` here without extra locking: every worker/response-worker thread
        // that could still be mutating it has already been joined above.
        Map<String, PendingEntry> dropped = new LinkedHashMap<>(pending);
        pending.clear();
        for (Map.Entry<String, PendingEntry> e : dropped.entrySet()) {
            logger.warning("session torn down with router_stan " + e.getKey() + " still pending (upstream_stan="
                    + e.getValue().upstreamStan() + "); abandoning");
        }
        if (!dropped.isEmpty()) {
            logger.warning("session teardown abandoned " + dropped.size() + " pending transaction(s)");
            stats.setGauge("pending_count", 0);
        }

        List<Map<String, Object>> abandonedTraces = trace.abandonInProgress();
        if (!abandonedTraces.isEmpty()) {
            logger.warning("session teardown left " + abandonedTraces.size() + " in-progress trace(s) incomplete");
        }
    }
}

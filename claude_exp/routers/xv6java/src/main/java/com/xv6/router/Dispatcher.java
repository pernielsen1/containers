package com.xv6.router;

import com.solab.iso8583.IsoMessage;
import com.solab.iso8583.MessageFactory;
import com.xv6.shared.ImsConnect;
import com.xv6.shared.IsoUtils;
import com.xv6.shared.Stats;
import com.xv6.shared.StopEvent;

import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * Worker pool. Routes 0100 upstream -> crypto -> downstream. Routes 0110/0130/0430 downstream ->
 * upstream (STAN lookup). Port of xv5's router/dispatcher.py.
 *
 * Concurrency mapping (see briefs/java_container_router.md): {@code queue.Queue(maxsize=N)} ->
 * {@link ArrayBlockingQueue}; {@code dict + threading.Lock} for the pending-STAN map ->
 * {@link ConcurrentHashMap}; {@code threading.Thread} x worker_threads -> plain daemon
 * {@link Thread}s (a fixed-size pool, matching the Python "not thread-per-message" design note).
 */
public final class Dispatcher {

    private static final Logger logger = Logger.getLogger(Dispatcher.class.getName());
    private static final int STAN_MODULUS = 1_000_000;
    private static final Set<String> RESPONSE_MTIS = Set.of("0110", "0130", "0430");
    private static final RoutedMessage POISON = new RoutedMessage(null, null, null, null);

    private final RouterConfig cfg;
    private final DownstreamConnection downstream;
    private final CryptoClient crypto;
    private final MessageFactory<IsoMessage> factory;
    private final Stats stats;
    private final StopEvent reconnectEvent;

    private final BlockingQueue<RoutedMessage> queue;
    private final Map<String, PendingEntry> pending = new ConcurrentHashMap<>();
    private final Object stanLock = new Object();
    private int stanCounter = 0;
    private final StopEvent stopEvent = new StopEvent();
    private final List<Thread> workerThreads = new ArrayList<>();
    private Thread reaperThread;

    public Dispatcher(RouterConfig cfg, DownstreamConnection downstream, CryptoClient crypto,
            MessageFactory<IsoMessage> factory, Stats stats, StopEvent reconnectEvent) {
        this.cfg = cfg;
        this.downstream = downstream;
        this.crypto = crypto;
        this.factory = factory;
        this.stats = stats;
        this.reconnectEvent = reconnectEvent;
        this.queue = new ArrayBlockingQueue<>(cfg.queueMaxsize());
    }

    private String nextStan() {
        synchronized (stanLock) {
            stanCounter = (stanCounter + 1) % STAN_MODULUS;
            return String.format("%06d", stanCounter);
        }
    }

    public void start() {
        for (int i = 0; i < cfg.workerThreads(); i++) {
            Thread t = new Thread(this::workerLoop, "worker-" + i);
            t.setDaemon(true);
            t.start();
            workerThreads.add(t);
        }
        reaperThread = new Thread(this::pendingReaper, "pending-reaper");
        reaperThread.setDaemon(true);
        reaperThread.start();
    }

    /** Blocking enqueue (backpressure). */
    public void submit(RoutedMessage msg) throws InterruptedException {
        queue.put(msg);
        stats.setGauge("queue_depth", queue.size());
        logger.fine("dispatcher: queued mti=" + msg.req().get("t") + " (queue_depth=" + queue.size() + ")");
    }

    private void workerLoop() {
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

    private void process(RoutedMessage msg) throws IOException {
        Map<String, String> req = msg.req();
        String mti = req.get("t");
        String pan = req.getOrDefault("2", "");
        String upstreamStan = req.getOrDefault("11", "");

        String routerStan = nextStan();

        Map<String, String> fwd = new LinkedHashMap<>(req);
        if ("0100".equals(mti)) {
            String result = crypto.validate("validate_0100", pan, req.getOrDefault("47", ""));
            if (!result.isEmpty()) {
                fwd.put("47", result);
            }
        }
        fwd.put("11", routerStan);

        byte[] encoded = IsoUtils.fromMap(factory, fwd).writeData();

        PendingEntry entry = new PendingEntry(msg.upConn(), msg.upWriteLock(), upstreamStan, System.nanoTime());
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

    /** Called from the ds-receiver thread. */
    public void handleResponse(Map<String, String> resp) {
        String mti = resp.get("t");
        if ("0810".equals(mti)) {
            return;
        }
        if (!RESPONSE_MTIS.contains(mti)) {
            logger.warning("unexpected response MTI from downstream: " + mti);
            return;
        }

        String routerStan = resp.getOrDefault("11", "");
        PendingEntry entry = pending.remove(routerStan);
        stats.setGauge("pending_count", pending.size());
        if (entry == null) {
            logger.warning("no pending entry for router_stan " + routerStan);
            return;
        }

        Map<String, String> fwd = new LinkedHashMap<>(resp);
        fwd.put("11", entry.upstreamStan());
        if ("0110".equals(mti)) {
            String pan = resp.getOrDefault("2", "");
            String result = crypto.validate("validate_0110", pan, resp.getOrDefault("47", ""));
            if (!result.isEmpty()) {
                fwd.put("47", result);
            }
        }

        byte[] encoded = IsoUtils.fromMap(factory, fwd).writeData();
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
                        byte[] encoded = IsoUtils.fromMap(factory, decline).writeData();
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

    /** Operator drain; returns dropped counts. */
    public Map<String, Integer> purge() {
        int droppedQueue = 0;
        while (queue.poll() != null) {
            droppedQueue++;
        }
        int droppedPending = pending.size();
        pending.clear();
        stats.setGauge("queue_depth", queue.size());
        stats.setGauge("pending_count", 0);

        Map<String, Integer> result = new LinkedHashMap<>();
        result.put("dropped_queue", droppedQueue);
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
        for (Thread t : workerThreads) {
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
    }
}

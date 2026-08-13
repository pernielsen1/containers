package com.router.router;

import com.solab.iso8583.IsoMessage;
import com.solab.iso8583.MessageFactory;
import com.router.shared.Framing;
import com.router.shared.FramingConfig;
import com.router.shared.ImsConnect;
import com.router.shared.IsoUtils;
import com.router.shared.Stats;
import com.router.shared.StopEvent;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.locks.ReentrantLock;
import java.util.logging.Handler;
import java.util.logging.Level;
import java.util.logging.LogRecord;
import java.util.logging.Logger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Port of router_py's tests/test_dispatcher_resilience.py. */
class DispatcherResilienceTest {

    private static final String SPEC_PATH = System.getProperty("user.dir") + "/config/test_spec.xml";

    /** A downstream that never actually connects a real socket - fine here since Dispatcher only
     * ever calls send(byte[]); no recv() path is exercised in these tests. */
    private static final class FakeDownstream {
        final java.util.List<byte[]> sent = new java.util.concurrent.CopyOnWriteArrayList<>();
        boolean fail = false;

        byte[] lastSent() {
            return sent.get(sent.size() - 1);
        }
    }

    private static Socket[] socketPair() throws IOException {
        try (ServerSocket server = new ServerSocket(0, 1, java.net.InetAddress.getLoopbackAddress())) {
            Socket client = new Socket();
            client.connect(new InetSocketAddress(server.getInetAddress(), server.getLocalPort()));
            Socket accepted = server.accept();
            return new Socket[]{client, accepted};
        }
    }

    private static RouterConfig makeCfg(int queueMaxsize, int pendingTtlSeconds, int workerThreads) {
        FramingConfig framing = new FramingConfig("", "ASCII", 4, Framing.DEFAULT_MAX_MESSAGE_BYTES);
        UpstreamConfig upstream = new UpstreamConfig(15000, framing, "server", "localhost", 5, false, null, null, null);
        DownstreamConfig downstream = new DownstreamConfig(
                "localhost", 15001, ImsConnect.toEbcdic("IRM0001", 8), ImsConnect.toEbcdic("CLIENT01", 8), false, null, null, null);
        CryptoConfig crypto = new CryptoConfig("localhost", 15002, "test-plugin-id", "test-bearer-token", false, null, null, null);
        return new RouterConfig(
                "test_router", 19100, upstream, downstream, crypto, SPEC_PATH, null, null, "INFO",
                workerThreads, workerThreads, 10, 40, queueMaxsize, pendingTtlSeconds, 5, 30, 2.0,
                "127.0.0.1", null);
    }

    /** Dispatcher only ever calls downstream.send(frame) directly through
     * DownstreamConnection - since that class opens two real IMS sockets on construction, these
     * white-box tests exercise Dispatcher.process()/handleResponse() logic without going through
     * a full DownstreamConnection, using a minimal stand-in that satisfies the same "send"
     * call site via a real connected socket pair instead. */
    private static final class TestHarness {
        final RouterConfig cfg;
        final Stats stats = new Stats(null);
        final MessageFactory<IsoMessage> factory;
        final StopEvent reconnectEvent = new StopEvent();
        final Socket dsA;
        final Socket dsB;
        final Dispatcher dispatcher;

        TestHarness(int queueMaxsize, int pendingTtlSeconds, int workerThreads) throws Exception {
            cfg = makeCfg(queueMaxsize, pendingTtlSeconds, workerThreads);
            factory = IsoUtils.loadFactory(SPEC_PATH);
            Socket[] pair = socketPair();
            dsA = pair[0];
            dsB = pair[1];
            DownstreamConnectionTestFactory downstreamStub = new DownstreamConnectionTestFactory(dsA);
            dispatcher = new Dispatcher(cfg, downstreamStub.asDownstream(), new NoOpCrypto(), factory, stats, reconnectEvent);
        }

        void close() {
            try {
                dsA.close();
            } catch (IOException ignored) {
            }
            try {
                dsB.close();
            } catch (IOException ignored) {
            }
        }
    }

    /** Wraps a plain connected socket behind the same send(byte[]) call Dispatcher uses, without
     * needing a real IMS Connect resume-TPIPE handshake. */
    private static final class DownstreamConnectionTestFactory {
        private final Socket sock;

        DownstreamConnectionTestFactory(Socket sock) {
            this.sock = sock;
        }

        DownstreamConnection asDownstream() throws Exception {
            java.lang.reflect.Constructor<DownstreamConnection> ctor =
                    DownstreamConnection.class.getDeclaredConstructor(Socket.class, Socket.class);
            ctor.setAccessible(true);
            return ctor.newInstance(sock, sock);
        }
    }

    /** Mirrors router_py's FakeCrypto test double: always returns "" without any network I/O. */
    private static final class NoOpCrypto extends CryptoClient {
        NoOpCrypto() throws IOException {
            super(new CryptoConfig("localhost", 1, "test-plugin-id", "test-bearer-token", false, null, null, null), 5, 30);
        }

        @Override
        public String validate(String endpoint, String pan, String f47, String routerStan) {
            return "";
        }
    }

    @Test
    void pendingEntryTtlExpirySendsLocalDecline() throws Exception {
        TestHarness h = new TestHarness(3, 1, 1);
        h.dispatcher.start();

        Socket upConn = new Socket();
        Socket testConn;
        Socket[] pair = socketPair();
        upConn = pair[0];
        testConn = pair[1];
        ReentrantLock writeLock = new ReentrantLock();
        try {
            Map<String, String> req = new LinkedHashMap<>();
            req.put("t", "0100");
            req.put("2", "4111111111111111");
            req.put("3", "000000");
            req.put("4", "000000000100");
            req.put("11", "000001");
            h.dispatcher.submit(new RoutedMessage(req, upConn, writeLock, upConn.getRemoteSocketAddress()));

            Thread.sleep(200);
            // Forwarded downstream over the real dsA/dsB socket pair; read it off dsB to drain,
            // proving exactly one frame was forwarded (no response ever arrives afterwards).
            testConn.setSoTimeout(5000);
            byte[] declineFrame = Framing.readMessage(testConn, new FramingConfig("", "ASCII", 4, Framing.DEFAULT_MAX_MESSAGE_BYTES));
            Map<String, String> resp = IsoUtils.toMap(h.factory.parseMessage(declineFrame, 0));
            assertEquals("000001", resp.get("11"));
            assertEquals("91", resp.get("39"));
        } finally {
            h.dispatcher.drainAndStop();
            h.close();
            upConn.close();
            testConn.close();
        }
    }

    @Test
    void submitBlocksWhenQueueIsFull() throws Exception {
        TestHarness h = new TestHarness(1, 100, 1);
        // Deliberately not calling dispatcher.start() - nothing drains the queue, so it fills up.

        Socket[] upPair = socketPair();
        Socket upConn = upPair[0];
        ReentrantLock writeLock = new ReentrantLock();
        try {
            Map<String, String> req = new LinkedHashMap<>();
            req.put("t", "0100");
            req.put("2", "4111111111111111");
            req.put("11", "000001");
            h.dispatcher.submit(new RoutedMessage(req, upConn, writeLock, upConn.getRemoteSocketAddress()));

            java.util.concurrent.atomic.AtomicBoolean secondSubmitted = new java.util.concurrent.atomic.AtomicBoolean(false);
            Thread t = new Thread(() -> {
                try {
                    Map<String, String> req2 = new LinkedHashMap<>();
                    req2.put("t", "0100");
                    req2.put("2", "4111111111111111");
                    req2.put("11", "000002");
                    h.dispatcher.submit(new RoutedMessage(req2, upConn, writeLock, upConn.getRemoteSocketAddress()));
                    secondSubmitted.set(true);
                } catch (InterruptedException ignored) {
                }
            });
            t.setDaemon(true);
            t.start();
            Thread.sleep(300);
            assertTrue(!secondSubmitted.get());

            drainOneFromQueue(h.dispatcher);
            t.join(2000);
            assertTrue(secondSubmitted.get());
        } finally {
            h.close();
            upConn.close();
            upPair[1].close();
        }
    }

    private static void drainOneFromQueue(Dispatcher dispatcher) throws Exception {
        java.lang.reflect.Field f = Dispatcher.class.getDeclaredField("queue");
        f.setAccessible(true);
        java.util.concurrent.BlockingQueue<?> queue = (java.util.concurrent.BlockingQueue<?>) f.get(dispatcher);
        queue.poll();
    }

    @Test
    void stanCollisionIsLogged() throws Exception {
        TestHarness h = new TestHarness(10, 100, 1);
        h.dispatcher.start();

        Socket[] pair = socketPair();
        Socket upConn = pair[0];
        Socket testConn = pair[1];
        ReentrantLock writeLock = new ReentrantLock();

        java.util.List<String> captured = new java.util.concurrent.CopyOnWriteArrayList<>();
        Handler captureHandler = new Handler() {
            @Override
            public void publish(LogRecord record) {
                if (record.getLevel().intValue() >= Level.SEVERE.intValue()) {
                    captured.add(record.getMessage());
                }
            }

            @Override
            public void flush() {
            }

            @Override
            public void close() {
            }
        };
        Logger dispatcherLogger = Logger.getLogger(Dispatcher.class.getName());
        dispatcherLogger.addHandler(captureHandler);

        try {
            int nextStanValue = getStanCounter(h.dispatcher) + 1;
            String nextStan = String.format("%06d", nextStanValue % 1_000_000);
            putPendingEntry(h.dispatcher, nextStan, new PendingEntry(upConn, writeLock, "000000", System.nanoTime()));

            Map<String, String> req = new LinkedHashMap<>();
            req.put("t", "0100");
            req.put("2", "4111111111111111");
            req.put("11", "000001");
            h.dispatcher.submit(new RoutedMessage(req, upConn, writeLock, upConn.getRemoteSocketAddress()));
            Thread.sleep(300);

            assertTrue(captured.stream().anyMatch(m -> m.contains("still outstanding")));
        } finally {
            dispatcherLogger.removeHandler(captureHandler);
            h.dispatcher.drainAndStop();
            h.close();
            upConn.close();
            testConn.close();
        }
    }

    @SuppressWarnings("unchecked")
    private static int getStanCounter(Dispatcher dispatcher) throws Exception {
        java.lang.reflect.Field f = Dispatcher.class.getDeclaredField("stanCounter");
        f.setAccessible(true);
        return (int) f.get(dispatcher);
    }

    @SuppressWarnings("unchecked")
    private static void putPendingEntry(Dispatcher dispatcher, String stan, PendingEntry entry) throws Exception {
        java.lang.reflect.Field f = Dispatcher.class.getDeclaredField("pending");
        f.setAccessible(true);
        Map<String, PendingEntry> pending = (Map<String, PendingEntry>) f.get(dispatcher);
        pending.put(stan, entry);
    }

    @Test
    void drainAndStopLogsAndClearsAbandonedPending() throws Exception {
        TestHarness h = new TestHarness(5, 100, 1);
        h.dispatcher.start();

        Socket[] pair = socketPair();
        Socket upConn = pair[0];
        Socket testConn = pair[1];
        ReentrantLock writeLock = new ReentrantLock();

        java.util.List<String> captured = new java.util.concurrent.CopyOnWriteArrayList<>();
        Handler captureHandler = new Handler() {
            @Override
            public void publish(LogRecord record) {
                if (record.getLevel().intValue() >= Level.WARNING.intValue()) {
                    captured.add(record.getMessage());
                }
            }

            @Override
            public void flush() {
            }

            @Override
            public void close() {
            }
        };
        Logger dispatcherLogger = Logger.getLogger(Dispatcher.class.getName());
        dispatcherLogger.addHandler(captureHandler);

        try {
            putPendingEntry(h.dispatcher, "000042", new PendingEntry(upConn, writeLock, "100042", System.nanoTime()));

            h.dispatcher.drainAndStop();

            assertEquals(0, getPendingSize(h.dispatcher));
            assertTrue(captured.stream().anyMatch(m -> m.contains("router_stan 000042 still pending")));
            assertTrue(captured.stream().anyMatch(m -> m.contains("abandoned 1 pending transaction")));
        } finally {
            dispatcherLogger.removeHandler(captureHandler);
            h.close();
            upConn.close();
            testConn.close();
        }
    }

    @SuppressWarnings("unchecked")
    private static int getPendingSize(Dispatcher dispatcher) throws Exception {
        java.lang.reflect.Field f = Dispatcher.class.getDeclaredField("pending");
        f.setAccessible(true);
        Map<String, PendingEntry> pending = (Map<String, PendingEntry>) f.get(dispatcher);
        return pending.size();
    }

    @Test
    void purgeDropsQueuedAndPendingCounts() throws Exception {
        TestHarness h = new TestHarness(5, 100, 1);
        // No start() - queue stays populated with nothing draining it.

        Socket[] pair = socketPair();
        Socket upConn = pair[0];
        ReentrantLock writeLock = new ReentrantLock();
        try {
            for (int i = 0; i < 3; i++) {
                Map<String, String> req = new LinkedHashMap<>();
                req.put("t", "0100");
                req.put("2", "4111111111111111");
                req.put("11", String.format("%06d", i));
                h.dispatcher.submit(new RoutedMessage(req, upConn, writeLock, upConn.getRemoteSocketAddress()));
            }

            putPendingEntry(h.dispatcher, "999999", new PendingEntry(upConn, writeLock, "000000", System.nanoTime()));

            Map<String, Integer> result = h.dispatcher.purge();
            assertEquals(3, result.get("dropped_queue"));
            assertEquals(1, result.get("dropped_pending"));
        } finally {
            h.close();
            upConn.close();
            pair[1].close();
        }
    }

    @Test
    void pendingSnapshotReportsAgeOldestFirst() throws Exception {
        TestHarness h = new TestHarness(5, 100, 1);
        // No start() - nothing drains `pending` out from under the direct injections below.

        Socket[] pair = socketPair();
        Socket upConn = pair[0];
        ReentrantLock writeLock = new ReentrantLock();
        try {
            long now = System.nanoTime();
            putPendingEntry(h.dispatcher, "000001",
                    new PendingEntry(upConn, writeLock, "100001", now - 5_000_000_000L));
            putPendingEntry(h.dispatcher, "000002",
                    new PendingEntry(upConn, writeLock, "100002", now - 1_000_000_000L));

            List<Map<String, Object>> snapshot = h.dispatcher.pendingSnapshot();
            assertEquals(List.of("000001", "000002"),
                    snapshot.stream().map(e -> e.get("router_stan")).toList());
            assertEquals("100001", snapshot.get(0).get("upstream_stan"));
            assertTrue((double) snapshot.get(0).get("age_seconds") > (double) snapshot.get(1).get("age_seconds"));
        } finally {
            h.close();
            upConn.close();
            pair[1].close();
        }
    }
}

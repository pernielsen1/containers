package com.router.router;

import com.solab.iso8583.IsoMessage;
import com.solab.iso8583.MessageFactory;
import com.router.shared.IsoUtils;
import com.router.shared.Stats;
import com.router.shared.StopEvent;

import java.io.IOException;
import java.net.Socket;
import java.net.SocketAddress;
import java.nio.charset.Charset;
import java.util.Map;
import java.util.concurrent.locks.ReentrantLock;
import java.util.function.BooleanSupplier;
import java.util.logging.Level;
import java.util.logging.Logger;

/** One live connection session. Owns the ds-receiver thread and up-server/client thread. Port of
 * router_py's router/session.py. */
public final class RouterSession {

    private static final Logger logger = Logger.getLogger(RouterSession.class.getName());
    private static final Charset CP500 = Charset.forName("Cp500");
    private static final byte[] PING_MARKER = "PING".getBytes(CP500);

    private final RouterConfig cfg;
    private final Stats stats;
    private final StopEvent stopEvent;
    private final DownstreamConnection downstream;
    private final CryptoClient crypto;
    final Dispatcher dispatcher;
    private final MessageFactory<IsoMessage> factory;
    // Upstream-facing leg can speak a different ISO 8583 encoding than the downstream leg (e.g.
    // router_2's EBCDIC partner vs the shared downstream_host's ASCII spec) - defaults to
    // `factory` when upstreamIsoEncoding isn't configured, so router_1 is unaffected.
    private final MessageFactory<IsoMessage> upstreamFactory;
    private final StopEvent reconnectEvent;

    private final Upstream.UpstreamClient upstreamClient;
    private volatile UpstreamRef upstreamRef;
    private final Object upRefLock = new Object();

    private record UpstreamRef(Socket conn, ReentrantLock writeLock) {
    }

    private RouterSession(RouterConfig cfg, Stats stats, StopEvent stopEvent, DownstreamConnection downstream,
            CryptoClient crypto, Dispatcher dispatcher, MessageFactory<IsoMessage> factory,
            MessageFactory<IsoMessage> upstreamFactory, StopEvent reconnectEvent) {
        this.cfg = cfg;
        this.stats = stats;
        this.stopEvent = stopEvent;
        this.downstream = downstream;
        this.crypto = crypto;
        this.dispatcher = dispatcher;
        this.factory = factory;
        this.upstreamFactory = upstreamFactory;
        this.reconnectEvent = reconnectEvent;
        this.upstreamClient = "client".equals(cfg.upstream().mode()) ? new Upstream.UpstreamClient(cfg.upstream()) : null;
    }

    public static RouterSession connect(RouterConfig cfg, Stats stats, StopEvent stopEvent) throws IOException {
        DownstreamConnection downstream = DownstreamConnection.connect(cfg.downstream());
        stats.setConnection("downstream", true);

        MessageFactory<IsoMessage> factory = IsoUtils.loadFactory(cfg.isoSpec());
        MessageFactory<IsoMessage> upstreamFactory = cfg.upstreamIsoEncoding() != null
                ? IsoUtils.loadFactory(cfg.isoSpec(), cfg.upstreamIsoEncoding())
                : factory;
        CryptoClient crypto = new CryptoClient(cfg.crypto(), cfg.cryptoBreakerThreshold(), cfg.cryptoBreakerCooldownSeconds());
        StopEvent reconnectEvent = new StopEvent();
        Dispatcher dispatcher = new Dispatcher(cfg, downstream, crypto, factory, stats, reconnectEvent, upstreamFactory);

        return new RouterSession(
                cfg, stats, stopEvent, downstream, crypto, dispatcher, factory, upstreamFactory, reconnectEvent);
    }

    public void runUntilDisconnect(Upstream.UpstreamServer srvSock) throws InterruptedException {
        dispatcher.start();

        Thread dsThread = new Thread(this::downstreamReceiver, "ds-receiver");
        dsThread.setDaemon(true);
        dsThread.start();

        Thread upThread;
        if ("server".equals(cfg.upstream().mode())) {
            upThread = new Thread(() -> serverUpstreamLoop(srvSock), "up-server");
        } else {
            upThread = new Thread(this::clientUpstreamLoop, "up-client");
        }
        upThread.setDaemon(true);
        upThread.start();

        while (true) {
            if (stopEvent.waitFor(1, java.util.concurrent.TimeUnit.SECONDS)) {
                break;
            }
            if (reconnectEvent.isSet()) {
                break;
            }
        }

        teardown(upThread);
        dsThread.join(5000);
    }

    private BooleanSupplier combinedEvent() {
        return () -> stopEvent.isSet() || reconnectEvent.isSet();
    }

    private void serverUpstreamLoop(Upstream.UpstreamServer srvSock) {
        UpstreamConn conn = srvSock.accept(combinedEvent());
        if (conn == null) {
            return;
        }
        handleUpstream(conn.socket(), conn.address(), conn.writeLock());
    }

    private void clientUpstreamLoop() {
        UpstreamConn conn = upstreamClient.connect(combinedEvent());
        if (conn == null) {
            return;
        }
        handleUpstream(conn.socket(), conn.address(), conn.writeLock());
    }

    private void handleUpstream(Socket conn, SocketAddress addr, ReentrantLock writeLock) {
        stats.setConnection("upstream", true);
        synchronized (upRefLock) {
            upstreamRef = new UpstreamRef(conn, writeLock);
        }

        try {
            while (true) {
                byte[] data;
                try {
                    data = Upstream.readUpstream(conn, cfg.upstream());
                } catch (IOException e) {
                    // Covers both a remote disconnect and a local close racing this blocked read
                    // during teardown.
                    logger.warning("upstream connection lost: " + e.getMessage());
                    reconnectEvent.set();
                    break;
                }

                Map<String, String> req;
                try {
                    req = IsoUtils.toMap(upstreamFactory.parseMessage(data, 0));
                } catch (Exception e) {
                    logger.log(Level.SEVERE, "failed to decode upstream message", e);
                    continue;
                }
                stats.recordRecv();

                String mti = req.get("t");
                logger.fine("upstream recv mti=" + mti);
                try {
                    if ("0100".equals(mti) || "0120".equals(mti) || "0420".equals(mti)) {
                        dispatcher.submit(new RoutedMessage(req, conn, writeLock, addr, data));
                    } else if ("0800".equals(mti)) {
                        forward0800(req);
                    } else {
                        logger.warning("unexpected upstream MTI: " + mti);
                    }
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    return;
                } catch (Exception e) {
                    // Any non-interrupt exception here must not kill this daemon thread silently -
                    // the session would then silently stop accepting upstream messages on this
                    // connection while the router happily continues processing downstream responses.
                    logger.log(Level.SEVERE, "unexpected error dispatching upstream message mti=" + mti, e);
                }
            }
        } finally {
            stats.setConnection("upstream", false);
            synchronized (upRefLock) {
                if (upstreamRef != null && upstreamRef.conn() == conn) {
                    upstreamRef = null;
                }
            }
        }
    }

    private void forward0800(Map<String, String> req) {
        byte[] encoded = IsoUtils.fromMap(factory, req).writeData();
        byte[] frame = com.router.shared.ImsConnect.buildFrame(
                0x00, cfg.downstream().irmId(), cfg.downstream().clientId(), "0800", encoded, null);
        try {
            downstream.send(frame);
            stats.recordSent();
            logger.fine("forwarded 0800 to downstream");
        } catch (IOException e) {
            // downstream can be closed by session teardown out from under this write (called
            // from the up-server/up-client read thread); reconnect_event will already be set
            // by the thread that's tearing the session down.
            logger.warning("failed to forward 0800 keepalive to downstream");
        }
    }

    private void forward0810(Map<String, String> resp) {
        UpstreamRef ref;
        synchronized (upRefLock) {
            ref = upstreamRef;
        }
        if (ref == null) {
            logger.warning("0810 received but no live upstream connection to forward to");
            return;
        }

        byte[] encoded = IsoUtils.fromMap(upstreamFactory, resp).writeData();
        try {
            ref.writeLock().lock();
            try {
                Upstream.writeUpstream(ref.conn(), encoded, cfg.upstream());
            } finally {
                ref.writeLock().unlock();
            }
            stats.recordSent();
            logger.fine("0810 forwarded to upstream");
        } catch (IOException e) {
            // The upstream connection can be closed by session teardown out from under this
            // write (called from the ds-receiver thread).
            logger.warning("failed to forward 0810 keepalive response to upstream");
        }
    }

    private void downstreamReceiver() {
        while (true) {
            byte[] data;
            try {
                data = downstream.recv();
            } catch (IOException e) {
                // Covers both a remote disconnect and a local close racing this blocked read
                // during teardown.
                logger.warning("downstream connection lost: " + e.getMessage());
                stats.setConnection("downstream", false);
                reconnectEvent.set();
                break;
            }

            if (data.length >= 4 && data[0] == PING_MARKER[0] && data[1] == PING_MARKER[1]
                    && data[2] == PING_MARKER[2] && data[3] == PING_MARKER[3]) {
                logger.fine("downstream PING pipe-cleaner received, skipping");
                continue;
            }

            Map<String, String> resp;
            try {
                resp = IsoUtils.toMap(factory.parseMessage(data, 0));
            } catch (Exception e) {
                logger.log(Level.SEVERE, "failed to decode downstream message", e);
                continue;
            }
            stats.recordRecv();
            logger.fine("downstream recv mti=" + resp.get("t"));

            try {
                if ("0810".equals(resp.get("t"))) {
                    forward0810(resp);
                } else {
                    dispatcher.submitResponse(resp, data);
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            } catch (Exception e) {
                // Any non-IO exception here must not kill this daemon thread silently - the
                // session would then silently stop processing downstream responses while the
                // router happily continues accepting upstream messages.
                logger.log(Level.SEVERE, "unexpected error dispatching downstream message mti=" + resp.get("t"), e);
            }
        }
    }

    private void teardown(Thread upThread) throws InterruptedException {
        dispatcher.drainAndStop();

        UpstreamRef ref;
        synchronized (upRefLock) {
            ref = upstreamRef;
            upstreamRef = null;
        }
        if (ref != null) {
            try {
                ref.conn().close();
            } catch (IOException ignored) {
            }
        }

        downstream.close();
        upThread.join(5000);
    }
}

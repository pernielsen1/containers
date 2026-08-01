package com.xv6.router;

import com.xv6.shared.Framing;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.util.concurrent.locks.ReentrantLock;
import java.util.function.BooleanSupplier;

/**
 * Port of router_py's router/upstream.py. {@code shouldStop} plays the role of Python's combined
 * stop_event/reconnect_event ({@code _OrEvent}) - callers pass e.g. {@code orEvent::isSet}.
 * Waits below poll every 200ms rather than blocking on a single condition variable (unlike
 * Python's threading.Event.wait, which wakes immediately when set); this trades a little latency
 * for a much simpler implementation, acceptable given this project's multi-second retry/reestablish
 * intervals.
 */
public final class Upstream {

    private Upstream() {
    }

    public static byte[] readUpstream(Socket conn, UpstreamConfig cfg) throws IOException {
        return Framing.readMessage(conn, cfg.framing());
    }

    public static void writeUpstream(Socket conn, byte[] data, UpstreamConfig cfg) throws IOException {
        Framing.writeMessage(conn, data, cfg.framing());
    }

    /** Listens on cfg.port. Created once outside the session loop (survives reconnects). */
    public static final class UpstreamServer {
        private final ServerSocket serverSocket;

        public UpstreamServer(UpstreamConfig cfg) throws IOException {
            serverSocket = new ServerSocket();
            serverSocket.setReuseAddress(true);
            serverSocket.bind(new InetSocketAddress(cfg.port()));
            serverSocket.setSoTimeout(1000);
        }

        /** Loops with a 1-second accept timeout; returns null on stop or a hard socket error. */
        public UpstreamConn accept(BooleanSupplier shouldStop) {
            while (!shouldStop.getAsBoolean()) {
                try {
                    Socket sock = serverSocket.accept();
                    return new UpstreamConn(sock, sock.getRemoteSocketAddress(), new ReentrantLock());
                } catch (SocketTimeoutException timeout) {
                    // loop, re-check shouldStop
                } catch (IOException e) {
                    return null;
                }
            }
            return null;
        }

        public void close() {
            try {
                serverSocket.close();
            } catch (IOException ignored) {
            }
        }
    }

    /** Connects out to cfg.host:cfg.port, retrying every cfg.retrySeconds(). */
    public static final class UpstreamClient {
        private final UpstreamConfig cfg;

        public UpstreamClient(UpstreamConfig cfg) {
            this.cfg = cfg;
        }

        public UpstreamConn connect(BooleanSupplier shouldStop) {
            while (!shouldStop.getAsBoolean()) {
                try {
                    Socket sock = new Socket();
                    sock.connect(new InetSocketAddress(cfg.host(), cfg.port()), 5000);
                    return new UpstreamConn(sock, sock.getRemoteSocketAddress(), new ReentrantLock());
                } catch (IOException e) {
                    if (!interruptibleWait(cfg.retrySeconds() * 1000L, shouldStop)) {
                        return null;
                    }
                }
            }
            return null;
        }

        private boolean interruptibleWait(long totalMillis, BooleanSupplier shouldStop) {
            long elapsed = 0;
            while (elapsed < totalMillis) {
                if (shouldStop.getAsBoolean()) {
                    return false;
                }
                try {
                    Thread.sleep(Math.min(200, totalMillis - elapsed));
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    return false;
                }
                elapsed += 200;
            }
            return true;
        }
    }
}

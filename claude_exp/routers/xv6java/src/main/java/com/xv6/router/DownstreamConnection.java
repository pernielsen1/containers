package com.xv6.router;

import com.xv6.shared.ImsConnect;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.Charset;
import java.util.concurrent.locks.ReentrantLock;

/** Dual-socket IMS session; thread-safe send via an internal lock. Port of xv5's
 * router/downstream.py DownstreamConnection. */
public final class DownstreamConnection {

    private static final Charset CP500 = Charset.forName("Cp500");

    private final Socket toSock;
    private final Socket fromSock;
    private final ReentrantLock sendLock = new ReentrantLock();

    private DownstreamConnection(Socket toSock, Socket fromSock) {
        this.toSock = toSock;
        this.fromSock = fromSock;
    }

    public static DownstreamConnection connect(DownstreamConfig cfg) throws IOException {
        Socket toSock = new Socket();
        toSock.connect(new InetSocketAddress(cfg.host(), cfg.port()), 5000);
        toSock.setSoTimeout(0);

        Socket fromSock = new Socket();
        fromSock.connect(new InetSocketAddress(cfg.host(), cfg.port()), 5000);
        fromSock.setSoTimeout(0);

        // Resume TPIPE on from-sock (no data).
        byte[] resume = ImsConnect.buildFrame(0x80, cfg.irmId(), cfg.clientId(), null, new byte[0], null);
        fromSock.getOutputStream().write(resume);
        fromSock.getOutputStream().flush();

        // Pipe-cleaner ping on to-sock.
        byte[] pingData = "1234 clean the pipes".getBytes(CP500);
        byte[] ping = ImsConnect.buildFrame(0x00, cfg.irmId(), cfg.clientId(), null, pingData, ImsConnect.PING_TRANSCODE);
        toSock.getOutputStream().write(ping);
        toSock.getOutputStream().flush();

        return new DownstreamConnection(toSock, fromSock);
    }

    public void send(byte[] frame) throws IOException {
        sendLock.lock();
        try {
            toSock.getOutputStream().write(frame);
            toSock.getOutputStream().flush();
        } finally {
            sendLock.unlock();
        }
    }

    /** Blocking read from the from-socket. */
    public byte[] recv() throws IOException {
        return ImsConnect.readResponse(fromSock);
    }

    public void close() {
        closeQuietly(toSock);
        closeQuietly(fromSock);
    }

    private static void closeQuietly(Socket sock) {
        try {
            sock.close();
        } catch (IOException ignored) {
        }
    }
}

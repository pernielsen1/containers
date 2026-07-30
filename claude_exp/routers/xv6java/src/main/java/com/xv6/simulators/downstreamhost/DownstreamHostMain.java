package com.xv6.simulators.downstreamhost;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.solab.iso8583.IsoMessage;
import com.solab.iso8583.MessageFactory;
import com.xv6.shared.CommandServer;
import com.xv6.shared.ImsConnect;
import com.xv6.shared.IsoUtils;
import com.xv6.shared.LogLevels;
import com.xv6.shared.Stats;
import com.xv6.shared.StopEvent;

import java.io.File;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.nio.charset.Charset;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.logging.Level;
import java.util.logging.Logger;

/** Simulates an IMS Connect authorization host. Port of xv5's
 * simulators/downstream_host/main.py. */
public final class DownstreamHostMain {

    private static final Logger logger = Logger.getLogger(DownstreamHostMain.class.getName());
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final Charset CP500 = Charset.forName("Cp500");
    // Both halves are EBCDIC, including the "PING" marker itself - it must match
    // RouterSession's skip-check byte-for-byte.
    private static final byte[] PING_MARKER = "PING".getBytes(CP500);

    private final Map<String, Object> cfg;
    private final MessageFactory<IsoMessage> factory;
    private final Map<String, Map<String, String>> pans;
    private final Stats stats;
    private final StopEvent stopEvent = new StopEvent();
    private final CommandServer cmd;

    private final Map<String, BlockingQueue<byte[]>> fromConnections = new ConcurrentHashMap<>();
    private int authCodeCounter = 0;
    private final Object authCodeLock = new Object();
    private ServerSocket listenSock;

    public static Map<String, Object> loadConfig(String path) throws IOException {
        Map<String, Object> cfg = new LinkedHashMap<>(MAPPER.readValue(new File(path), Map.class));
        String baseDir = new File(path).getAbsoluteFile().getParent();
        cfg.put("iso_spec", resolve(baseDir, (String) cfg.get("iso_spec")));
        cfg.put("pans_defined", resolve(baseDir, (String) cfg.get("pans_defined")));
        return cfg;
    }

    private static String resolve(String baseDir, String relative) {
        return Path.of(baseDir).resolve(relative).normalize().toString();
    }

    @SuppressWarnings("unchecked")
    public DownstreamHostMain(Map<String, Object> cfg) throws IOException {
        this.cfg = cfg;
        this.factory = IsoUtils.loadFactory((String) cfg.get("iso_spec"));
        this.pans = (Map<String, Map<String, String>>) (Map<String, ?>) MAPPER.readValue(
                new File((String) cfg.get("pans_defined")), Map.class);

        Object yellow = cfg.get("yellow_threshold_seconds");
        this.stats = new Stats(yellow == null ? null : ((Number) yellow).intValue());
        this.cmd = new CommandServer((Integer) cfg.get("command_port"), stats, stopEvent, "127.0.0.1", null);
    }

    private String nextAuthCode() {
        synchronized (authCodeLock) {
            authCodeCounter++;
            return String.format("%06d", authCodeCounter);
        }
    }

    /** Polls for up to timeoutMs - the from-conn's resume-TPIPE can still be in flight when the
     * to-conn's first frame (the pipe-cleaner ping) arrives; polling avoids dropping frames on
     * that race. */
    private BlockingQueue<byte[]> waitForFromConn(String clientIdKey, long timeoutMs) throws InterruptedException {
        long deadline = System.currentTimeMillis() + timeoutMs;
        while (System.currentTimeMillis() < deadline) {
            BlockingQueue<byte[]> q = fromConnections.get(clientIdKey);
            if (q != null) {
                return q;
            }
            Thread.sleep(50);
        }
        return null;
    }

    private void handleFromConn(Socket conn, String clientIdKey) {
        BlockingQueue<byte[]> q = new LinkedBlockingQueue<>();
        fromConnections.put(clientIdKey, q);
        logger.info("registered from-conn for client_id=" + clientIdKey);
        try {
            while (!stopEvent.isSet()) {
                byte[] item;
                try {
                    item = q.poll(1, java.util.concurrent.TimeUnit.SECONDS);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    return;
                }
                if (item == null) {
                    continue;
                }
                try {
                    ImsConnect.writeResponse(conn, item);
                } catch (IOException e) {
                    logger.warning("failed to write response on from-conn for " + clientIdKey);
                    return;
                }
            }
        } finally {
            fromConnections.remove(clientIdKey, q);
            closeQuietly(conn);
        }
    }

    private void handleToConn(Socket conn, String clientIdKey) {
        try {
            while (true) {
                ImsConnect.ImsRequest req;
                try {
                    req = ImsConnect.readRequest(conn);
                } catch (IOException e) {
                    return;
                }
                routeFrame(clientIdKey, req.transcode(), req.isoData());
            }
        } finally {
            closeQuietly(conn);
        }
    }

    private void routeFrame(String clientIdKey, byte[] transcode, byte[] isoData) {
        if (java.util.Arrays.equals(transcode, ImsConnect.PING_TRANSCODE)) {
            try {
                BlockingQueue<byte[]> q = waitForFromConn(clientIdKey, 2000);
                if (q != null) {
                    byte[] pingReply = concat(PING_MARKER, "PIPES cleaned".getBytes(CP500));
                    q.put(pingReply);
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
            return;
        }

        Map<String, String> req;
        try {
            req = IsoUtils.toMap(factory.parseMessage(isoData, 0));
        } catch (Exception e) {
            logger.log(Level.SEVERE, "failed to decode request from client_id=" + clientIdKey, e);
            return;
        }

        stats.recordRecv();
        String mti = req.get("t");
        Map<String, String> resp;
        if ("0800".equals(mti)) {
            resp = new LinkedHashMap<>(req);
            resp.put("t", "0810");
        } else if ("0120".equals(mti)) {
            resp = new LinkedHashMap<>(req);
            resp.put("t", "0130");
            resp.put("39", "00");
        } else if ("0420".equals(mti)) {
            resp = new LinkedHashMap<>(req);
            resp.put("t", "0430");
            resp.put("39", "00");
        } else if ("0100".equals(mti)) {
            resp = process0100(req);
        } else {
            logger.warning("unhandled MTI from upstream via router: " + mti);
            return;
        }

        byte[] encoded = IsoUtils.fromMap(factory, resp).writeData();

        try {
            BlockingQueue<byte[]> q = waitForFromConn(clientIdKey, 2000);
            if (q == null) {
                logger.warning("no from-conn registered for client_id=" + clientIdKey + "; dropping response");
                return;
            }
            q.put(encoded);
            stats.recordSent();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private Map<String, String> process0100(Map<String, String> req) {
        String pan = req.getOrDefault("2", "");
        Map<String, Object> f47 = IsoUtils.f47Decode(req.getOrDefault("47", ""));

        String rc;
        if (!pans.containsKey(pan)) {
            rc = "01";
        } else if (!"00".equals(String.valueOf(f47.getOrDefault("response_code", "00")))) {
            rc = "01";
        } else {
            rc = "00";
        }

        Map<String, String> resp = new LinkedHashMap<>(req);
        resp.put("t", "0110");
        resp.put("39", rc);
        if ("00".equals(rc)) {
            resp.put("38", nextAuthCode());
        }

        // Every response must echo f47 back: crypto_host's ARPC step only runs on
        // validate_0110, and the original f55 cryptogram/ATC can only reach that call by
        // round-tripping the request's f47 into the response.
        f47.put("message_type", "0110");
        f47.put("response_code", rc);
        resp.put("47", IsoUtils.f47Encode(f47));
        return resp;
    }

    private void dispatchNewConn(Socket conn) {
        ImsConnect.ImsRequest first;
        try {
            first = ImsConnect.readRequest(conn);
        } catch (IOException e) {
            closeQuietly(conn);
            return;
        }

        String clientIdKey = new String(first.clientId(), CP500);
        if (first.irmF0() == 0x80) {
            handleFromConn(conn, clientIdKey);
        } else {
            if (first.transcode().length > 0) {
                routeFrame(clientIdKey, first.transcode(), first.isoData());
            }
            handleToConn(conn, clientIdKey);
        }
    }

    private void acceptLoop() {
        while (!stopEvent.isSet()) {
            Socket conn;
            try {
                conn = listenSock.accept();
            } catch (SocketTimeoutException timeout) {
                continue;
            } catch (IOException e) {
                break;
            }
            Thread t = new Thread(() -> dispatchNewConn(conn));
            t.setDaemon(true);
            t.start();
        }
    }

    public void start() throws IOException {
        cmd.start();
        listenSock = new ServerSocket();
        listenSock.setReuseAddress(true);
        listenSock.bind(new InetSocketAddress((Integer) cfg.get("port")));
        listenSock.setSoTimeout(1000);
        logger.info("downstream host listening on port " + cfg.get("port"));
        Thread t = new Thread(this::acceptLoop, "accept-loop");
        t.setDaemon(true);
        t.start();
    }

    public void runForever() throws IOException, InterruptedException {
        start();
        stopEvent.await();
        if (listenSock != null) {
            closeQuietly(listenSock);
        }
    }

    private static byte[] concat(byte[] a, byte[] b) {
        byte[] out = new byte[a.length + b.length];
        System.arraycopy(a, 0, out, 0, a.length);
        System.arraycopy(b, 0, out, a.length, b.length);
        return out;
    }

    private static void closeQuietly(Socket sock) {
        try {
            sock.close();
        } catch (IOException ignored) {
        }
    }

    private static void closeQuietly(ServerSocket sock) {
        try {
            sock.close();
        } catch (IOException ignored) {
        }
    }

    public static void main(String[] args) throws Exception {
        String configPath = null;
        for (int i = 0; i < args.length; i++) {
            if ("--config".equals(args[i]) && i + 1 < args.length) {
                configPath = args[i + 1];
            }
        }
        if (configPath == null) {
            throw new IllegalArgumentException("usage: DownstreamHostMain --config <path>");
        }
        Map<String, Object> cfg = loadConfig(configPath);
        Logger.getLogger("").setLevel(LogLevels.parse("INFO"));
        try {
            new DownstreamHostMain(cfg).runForever();
            // See CryptoHostMain.main() - HttpServer's internal dispatcher thread isn't a
            // daemon thread, so an explicit exit is needed once the stop event has been honored.
            System.exit(0);
        } catch (Exception e) {
            e.printStackTrace();
            System.exit(1);
        }
    }
}

package com.xv6.simulators.upstreamhost;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.solab.iso8583.IsoMessage;
import com.solab.iso8583.MessageFactory;
import com.sun.net.httpserver.HttpExchange;
import com.xv6.shared.CommandServer;
import com.xv6.shared.Framing;
import com.xv6.shared.FramingConfig;
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
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.LinkedHashMap;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.logging.Level;
import java.util.logging.Logger;

/** Simulates an upstream card network client: sends ISO 8583 0100s from a CSV, collects 0110
 * responses. Port of xv5's simulators/upstream_host/main.py. */
public final class UpstreamHostMain {

    private static final Logger logger = Logger.getLogger(UpstreamHostMain.class.getName());
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final Set<String> RESPONSE_MTIS = Set.of("0110", "0130", "0430");
    private static final int STAN_MODULUS = 1_000_000;

    private final Map<String, Object> cfg;
    private final MessageFactory<IsoMessage> factory;
    private final FramingConfig framing;
    private final String mode;
    private final long ping0800Millis;
    private final String inputDir;

    private final Stats stats;
    private final StopEvent stopEvent = new StopEvent();
    private final CommandServer cmd;

    private volatile Socket conn;
    private final Object connLock = new Object();

    private final AtomicInteger stanCounter = new AtomicInteger(0);
    private final Map<String, Map<String, String>> pending = new ConcurrentHashMap<>();
    private final List<Map<String, String>> results = new ArrayList<>();
    private final Object resultsLock = new Object();

    private ServerSocket listenSock;

    public static Map<String, Object> loadConfig(String path) throws IOException {
        Map<String, Object> cfg = new LinkedHashMap<>(MAPPER.readValue(new File(path), Map.class));
        String baseDir = new File(path).getAbsoluteFile().getParent();
        cfg.put("iso_spec", resolve(baseDir, (String) cfg.get("iso_spec")));
        cfg.put("input_dir", resolve(baseDir, (String) cfg.getOrDefault("input_dir", "input")));
        return cfg;
    }

    private static String resolve(String baseDir, String relative) {
        return Path.of(baseDir).resolve(relative).normalize().toString();
    }

    @SuppressWarnings("unchecked")
    public UpstreamHostMain(Map<String, Object> cfg) throws IOException {
        this.cfg = cfg;
        this.factory = IsoUtils.loadFactory((String) cfg.get("iso_spec"));

        Map<String, Object> framingMap = (Map<String, Object>) cfg.get("framing");
        this.framing = new FramingConfig(
                (String) framingMap.get("header_hex"),
                (String) framingMap.get("length_field_type"),
                ((Number) framingMap.get("length_field_bytes")).intValue(),
                Framing.DEFAULT_MAX_MESSAGE_BYTES);

        this.mode = (String) cfg.getOrDefault("mode", "client");
        Object ping = cfg.get("ping_0800_seconds");
        this.ping0800Millis = (ping == null ? 30 : ((Number) ping).longValue()) * 1000L;
        this.inputDir = (String) cfg.get("input_dir");
        Files.createDirectories(Path.of(inputDir));

        Object yellow = cfg.get("yellow_threshold_seconds");
        this.stats = new Stats(yellow == null ? null : ((Number) yellow).intValue());
        this.cmd = new CommandServer((Integer) cfg.get("command_port"), stats, stopEvent, "127.0.0.1", null);
        registerRoutes();
    }

    private Path csvPath() {
        return Path.of(inputDir, "test_cases.csv");
    }

    private String nextStan() {
        int stan = stanCounter.incrementAndGet() % STAN_MODULUS;
        return String.format("%06d", stan);
    }

    private List<Map<String, String>> readCsv(Path csvPath) throws IOException {
        List<String> lines = Files.readAllLines(csvPath, StandardCharsets.UTF_8);
        if (lines.isEmpty()) {
            return List.of();
        }
        String headerLine = lines.get(0);
        if (headerLine.startsWith("﻿")) {
            headerLine = headerLine.substring(1);
        }
        String[] headers = headerLine.split(";", -1);

        List<Map<String, String>> rows = new ArrayList<>();
        for (int i = 1; i < lines.size(); i++) {
            String line = lines.get(i);
            if (line.isEmpty()) {
                continue;
            }
            String[] values = line.split(";", -1);
            Map<String, String> row = new LinkedHashMap<>();
            for (int j = 0; j < headers.length && j < values.length; j++) {
                row.put(headers[j], values[j]);
            }
            rows.add(row);
        }
        return rows;
    }

    private void sendLoop(Socket conn, List<Map<String, String>> rows) {
        for (Map<String, String> row : rows) {
            if (stopEvent.isSet()) {
                break;
            }
            String stan = nextStan();
            // Column names are ISO 8583 field numbers; non-matching columns (e.g. expected_39)
            // are silently ignored. Field 11 (STAN) is always overwritten by the sender.
            Map<String, String> msg = new LinkedHashMap<>();
            for (Map.Entry<String, String> e : row.entrySet()) {
                if (IsoUtils.isKnownField(e.getKey())) {
                    msg.put(e.getKey(), e.getValue());
                }
            }
            msg.put("t", "0100");
            msg.put("11", stan);

            pending.put(stan, row);

            try {
                byte[] encoded = IsoUtils.fromMap(factory, msg).writeData();
                Framing.writeMessage(conn, encoded, framing);
                stats.recordSent();
            } catch (IOException e) {
                break;
            }
            try {
                Thread.sleep(20);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            }
        }
    }

    private void receiveLoop(Socket conn, AtomicBoolean discEvt) {
        while (!discEvt.get()) {
            byte[] data;
            try {
                data = Framing.readMessage(conn, framing);
            } catch (IOException e) {
                discEvt.set(true);
                break;
            }

            Map<String, String> resp;
            try {
                resp = IsoUtils.toMap(factory.parseMessage(data, 0));
            } catch (Exception e) {
                logger.log(Level.SEVERE, "failed to decode router response", e);
                continue;
            }
            stats.recordRecv();

            String mti = resp.get("t");
            if ("0810".equals(mti)) {
                continue;
            }
            if (!RESPONSE_MTIS.contains(mti)) {
                logger.warning("unexpected response MTI: " + mti);
                continue;
            }

            String stan = resp.getOrDefault("11", "");
            Map<String, String> row = pending.remove(stan);
            if (row == null) {
                logger.warning("no pending request for STAN " + stan);
                continue;
            }

            Map<String, String> merged = new LinkedHashMap<>(row);
            for (Map.Entry<String, String> e : resp.entrySet()) {
                merged.put("resp_" + e.getKey(), e.getValue());
            }
            synchronized (resultsLock) {
                results.add(merged);
            }
        }
    }

    private void keepaliveLoop(Socket conn, AtomicBoolean discEvt) {
        while (!discEvt.get() && !stopEvent.isSet()) {
            try {
                byte[] data = IsoUtils.build0800(factory);
                Framing.writeMessage(conn, data, framing);
                stats.recordSent();
            } catch (IOException e) {
                return;
            }
            // Sending first, then waiting, is required - waiting first would produce a dead
            // ping_0800_seconds window on every new connection.
            long elapsed = 0;
            while (elapsed < ping0800Millis) {
                if (discEvt.get() || stopEvent.isSet()) {
                    return;
                }
                try {
                    Thread.sleep(Math.min(1000, ping0800Millis - elapsed));
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    return;
                }
                elapsed += 1000;
            }
        }
    }

    private void runConnection(Socket sock) {
        synchronized (connLock) {
            conn = sock;
        }
        stats.setConnection("router", true);

        AtomicBoolean discEvt = new AtomicBoolean(false);
        Thread recvThread = new Thread(() -> receiveLoop(sock, discEvt), "recv-loop");
        recvThread.setDaemon(true);
        recvThread.start();
        Thread keepaliveThread = new Thread(() -> keepaliveLoop(sock, discEvt), "keepalive-loop");
        keepaliveThread.setDaemon(true);
        keepaliveThread.start();

        while (!discEvt.get() && !stopEvent.isSet()) {
            try {
                Thread.sleep(200);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                break;
            }
        }

        synchronized (connLock) {
            if (conn == sock) {
                conn = null;
            }
        }
        stats.setConnection("router", false);
        closeQuietly(sock);
        try {
            recvThread.join(2000);
            keepaliveThread.join(2000);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    @SuppressWarnings("unchecked")
    private void clientConnectLoop() {
        Map<String, Object> routerCfg = (Map<String, Object>) cfg.get("router");
        long retryMs = ((Number) cfg.getOrDefault("retry_seconds", 5)).longValue() * 1000L;
        while (!stopEvent.isSet()) {
            Socket sock = new Socket();
            try {
                sock.connect(new InetSocketAddress((String) routerCfg.get("host"), (Integer) routerCfg.get("port")), 5000);
            } catch (IOException e) {
                try {
                    stopEvent.waitFor(retryMs, TimeUnit.MILLISECONDS);
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    return;
                }
                continue;
            }
            runConnection(sock);
        }
    }

    @SuppressWarnings("unchecked")
    private void serverAcceptLoop() throws IOException {
        Map<String, Object> routerCfg = (Map<String, Object>) cfg.get("router");
        listenSock = new ServerSocket();
        listenSock.setReuseAddress(true);
        listenSock.bind(new InetSocketAddress((Integer) routerCfg.get("port")));
        listenSock.setSoTimeout(1000);

        while (!stopEvent.isSet()) {
            Socket conn;
            try {
                conn = listenSock.accept();
            } catch (SocketTimeoutException e) {
                continue;
            } catch (IOException e) {
                break;
            }
            runConnection(conn);
        }
    }

    private void registerRoutes() {
        cmd.register("/upload", List.of("POST"), false, this::handleUpload);
        cmd.register("/start", List.of("GET"), false, this::handleStart);
        cmd.register("/results", List.of("GET"), false, exchange -> {
            List<Map<String, String>> snapshot;
            synchronized (resultsLock) {
                snapshot = new ArrayList<>(results);
            }
            CommandServer.sendJson(exchange, 200, snapshot);
        });
    }

    private void handleUpload(HttpExchange exchange) throws IOException {
        byte[] fileBytes = parseMultipartFile(exchange);
        if (fileBytes == null) {
            CommandServer.sendJson(exchange, 400, Map.of("error", "no file provided"));
            return;
        }
        Files.write(csvPath(), fileBytes);
        CommandServer.sendJson(exchange, 200, Map.of("status", "ok"));
    }

    private void handleStart(HttpExchange exchange) throws IOException {
        List<Map<String, String>> rows;
        try {
            rows = readCsv(csvPath());
        } catch (IOException e) {
            CommandServer.sendJson(exchange, 400, Map.of("error", "no CSV uploaded"));
            return;
        }

        Socket sockNow;
        synchronized (connLock) {
            sockNow = conn;
        }
        if (sockNow == null) {
            CommandServer.sendJson(exchange, 503, Map.of("error", "not connected to router"));
            return;
        }

        Thread t = new Thread(() -> sendLoop(sockNow, rows), "send-loop");
        t.setDaemon(true);
        t.start();
        CommandServer.sendJson(exchange, 200, Map.of("rows", rows.size()));
    }

    /** Minimal multipart/form-data parser for a single-file "file" field, matching what
     * run_test.sh's {@code curl -F "file=@..."} upload produces (Flask's request.files.get
     * equivalent) - not a general-purpose multipart implementation. */
    private byte[] parseMultipartFile(HttpExchange exchange) throws IOException {
        String contentType = exchange.getRequestHeaders().getFirst("Content-Type");
        if (contentType == null || !contentType.contains("multipart/form-data")) {
            return null;
        }
        String boundary = null;
        for (String part : contentType.split(";")) {
            part = part.trim();
            if (part.startsWith("boundary=")) {
                boundary = part.substring("boundary=".length());
                if (boundary.startsWith("\"") && boundary.endsWith("\"")) {
                    boundary = boundary.substring(1, boundary.length() - 1);
                }
            }
        }
        if (boundary == null) {
            return null;
        }

        byte[] body = exchange.getRequestBody().readAllBytes();
        String headerView = new String(body, StandardCharsets.ISO_8859_1);
        int filenameIdx = headerView.indexOf("filename=");
        if (filenameIdx < 0) {
            return null;
        }
        int headerEnd = headerView.indexOf("\r\n\r\n", filenameIdx);
        if (headerEnd < 0) {
            return null;
        }
        int contentStart = headerEnd + 4;

        byte[] boundaryBytes = ("--" + boundary).getBytes(StandardCharsets.US_ASCII);
        int nextBoundaryIdx = indexOf(body, boundaryBytes, contentStart);
        int contentEnd = nextBoundaryIdx >= 0 ? nextBoundaryIdx : body.length;
        if (contentEnd >= 2 && body[contentEnd - 1] == '\n' && body[contentEnd - 2] == '\r') {
            contentEnd -= 2;
        }
        return Arrays.copyOfRange(body, contentStart, contentEnd);
    }

    private static int indexOf(byte[] data, byte[] pattern, int fromIndex) {
        outer:
        for (int i = fromIndex; i <= data.length - pattern.length; i++) {
            for (int j = 0; j < pattern.length; j++) {
                if (data[i + j] != pattern[j]) {
                    continue outer;
                }
            }
            return i;
        }
        return -1;
    }

    public void start() throws IOException {
        cmd.start();
        if ("server".equals(mode)) {
            Thread t = new Thread(() -> {
                try {
                    serverAcceptLoop();
                } catch (IOException e) {
                    logger.log(Level.SEVERE, "server accept loop failed", e);
                }
            }, "accept-loop");
            t.setDaemon(true);
            t.start();
        } else {
            Thread t = new Thread(this::clientConnectLoop, "connect-loop");
            t.setDaemon(true);
            t.start();
        }
    }

    public void runForever() throws IOException, InterruptedException {
        start();
        stopEvent.await();
        if (listenSock != null) {
            closeQuietly(listenSock);
        }
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
            throw new IllegalArgumentException("usage: UpstreamHostMain --config <path>");
        }
        Map<String, Object> cfg = loadConfig(configPath);
        Logger.getLogger("").setLevel(LogLevels.parse("INFO"));
        try {
            new UpstreamHostMain(cfg).runForever();
            // See CryptoHostMain.main() - HttpServer's internal dispatcher thread isn't a
            // daemon thread, so an explicit exit is needed once the stop event has been honored.
            System.exit(0);
        } catch (Exception e) {
            e.printStackTrace();
            System.exit(1);
        }
    }
}

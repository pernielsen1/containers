package com.xv6.simulators.cryptohost;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import com.xv6.shared.CommandServer;
import com.xv6.shared.IsoUtils;
import com.xv6.shared.LogLevels;
import com.xv6.shared.Stats;
import com.xv6.shared.StopEvent;

import java.io.File;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.logging.Level;
import java.util.logging.Logger;

/** Stateless HTTP service for cryptographic validation. Port of router_py's
 * simulators/crypto_host/main.py. */
public final class CryptoHostMain {

    private static final Logger logger = Logger.getLogger(CryptoHostMain.class.getName());
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final Map<String, Object> cfg;
    private final Map<String, Map<String, String>> pans;
    private final Stats stats;
    private final StopEvent stopEvent = new StopEvent();
    private final CommandServer cmd;

    public static Map<String, Object> loadConfig(String path) throws IOException {
        Map<String, Object> cfg = new LinkedHashMap<>(MAPPER.readValue(new File(path), Map.class));
        String baseDir = new File(path).getAbsoluteFile().getParent();
        cfg.put("pans_defined", resolve(baseDir, (String) cfg.get("pans_defined")));
        return cfg;
    }

    private static String resolve(String baseDir, String relative) {
        return Path.of(baseDir).resolve(relative).normalize().toString();
    }

    public CryptoHostMain(Map<String, Object> cfg) throws IOException {
        this.cfg = cfg;
        this.pans = MAPPER.readValue(
                new File((String) cfg.get("pans_defined")), new TypeReference<Map<String, Map<String, String>>>() {
                });

        Object yellow = cfg.get("yellow_threshold_seconds");
        this.stats = new Stats(yellow == null ? null : ((Number) yellow).intValue());
        Object cmdPort = cfg.get("command_port");
        this.cmd = new CommandServer(
                cmdPort == null ? 8082 : ((Number) cmdPort).intValue(),
                stats, stopEvent, "127.0.0.1", null);
    }

    // Stub: no PIN/ARQC/CVV2/AAV math - just reports whether the PAN is provisioned. Real
    // cryptographic validation lives in routers/crypto_host/ (the shared container); this stub
    // exists so router_java can still be built/tested standalone without it.
    private String validate(String pan, String f47Str) {
        Map<String, Object> data = IsoUtils.f47Decode(f47Str);
        data.put("response_code", pans.containsKey(pan) ? "00" : "14");
        return IsoUtils.f47Encode(data);
    }

    @SuppressWarnings("unchecked")
    private void registerFortanixRoute(HttpServer server, String pluginId, String bearerToken) {
        server.createContext("/sys/v1/plugins/" + pluginId, exchange -> {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                CommandServer.sendText(exchange, 405, "Method Not Allowed");
                return;
            }

            String authHeader = exchange.getRequestHeaders().getFirst("Authorization");
            if (authHeader == null || !authHeader.equals("Bearer " + bearerToken)) {
                CommandServer.sendJson(exchange, 401, Map.of("error", "unauthorized"));
                return;
            }

            try {
                stats.recordRecv();
                Map<String, Object> body = MAPPER.readValue(exchange.getRequestBody().readAllBytes(), Map.class);
                String operation = String.valueOf(body.getOrDefault("operation", ""));
                String pan = String.valueOf(body.getOrDefault("f2", ""));
                String f47 = String.valueOf(body.getOrDefault("f47", ""));
                // Not part of the Fortanix plugin contract - passed through purely so this
                // actor's logs can be joined with the router's logs on the same transaction
                // (empty when a caller doesn't send one, e.g. tests hitting this route directly).
                String routerStan = String.valueOf(body.getOrDefault("router_stan", ""));

                if (!operation.equals("validate_0100") && !operation.equals("validate_0110")) {
                    CommandServer.sendJson(exchange, 400, Map.of("error", "unknown operation: " + operation));
                    return;
                }

                logger.fine("validate pan=" + pan + " router_stan=" + routerStan);
                String result = validate(pan, f47);
                Map<String, Object> responseData = Map.of("f47", result);
                String responseJson = MAPPER.writeValueAsString(responseData);
                String base64Encoded = Base64.getEncoder().encodeToString(responseJson.getBytes(StandardCharsets.UTF_8));

                stats.recordSent();
                exchange.getResponseHeaders().set("Content-Type", "application/json");
                exchange.sendResponseHeaders(200, 0);
                exchange.getResponseBody().write(("\"" + base64Encoded + "\"").getBytes(StandardCharsets.UTF_8));
                exchange.close();
            } catch (Exception e) {
                logger.log(Level.WARNING, "Error processing request: " + e.getMessage());
                try {
                    CommandServer.sendJson(exchange, 500, Map.of("error", "internal error"));
                } catch (IOException ioe) {
                    logger.log(Level.WARNING, "Failed to send error response: " + ioe.getMessage());
                }
            }
        });
    }

    public void start() throws IOException {
        cmd.start();

        String pluginId = String.valueOf(cfg.getOrDefault("plugin_id", "default-plugin-id"));
        String bearerToken = String.valueOf(cfg.getOrDefault("bearer_token", "default-bearer-token"));

        int port = ((Number) cfg.get("port")).intValue();
        HttpServer validateServer = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
        registerFortanixRoute(validateServer, pluginId, bearerToken);
        logger.info("crypto host listening on port " + port);
        validateServer.setExecutor(Executors.newCachedThreadPool(runnable -> {
            Thread t = new Thread(runnable);
            t.setDaemon(true);
            return t;
        }));
        validateServer.start();
    }

    public void runForever() throws IOException, InterruptedException {
        start();
        stopEvent.await();
    }

    public static void main(String[] args) throws Exception {
        String configPath = null;
        for (int i = 0; i < args.length; i++) {
            if ("--config".equals(args[i]) && i + 1 < args.length) {
                configPath = args[i + 1];
            }
        }
        if (configPath == null) {
            throw new IllegalArgumentException("usage: CryptoHostMain --config <path>");
        }
        Map<String, Object> cfg = loadConfig(configPath);
        Logger.getLogger("").setLevel(LogLevels.parse("INFO"));
        try {
            new CryptoHostMain(cfg).runForever();
            // com.sun.net.httpserver.HttpServer's internal dispatcher thread is not a daemon
            // thread (confirmed: the process stayed alive after /stop with only that thread
            // left), so unlike router_py (where every thread genuinely is a daemon thread and the
            // interpreter exits on its own), this JVM needs an explicit exit once the stop event
            // has been honored.
            System.exit(0);
        } catch (Exception e) {
            e.printStackTrace();
            System.exit(1);
        }
    }
}

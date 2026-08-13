package com.router.shared;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * HTTP command/stats API shared by every actor (router, simulators), backed by the JDK's built-in
 * {@link HttpServer} - zero extra dependency, matching the "standard Java is enough" philosophy
 * already applied to crypto. Port of router_py's shared/command_server.py.
 */
public final class CommandServer {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final HttpServer server;
    private final Stats stats;
    private final StopEvent stopEvent;
    private final String authToken;
    private final LogBuffer logBuffer = new LogBuffer(2000);

    public CommandServer(int port, Stats stats, StopEvent stopEvent, String bindHost, String authToken)
            throws IOException {
        this.stats = stats;
        this.stopEvent = stopEvent;
        this.authToken = authToken;

        // Root logger gets the LogBuffer handler as a side effect of construction - mirrors the
        // Python version's ordering requirement: configure logging (levels, handlers) before
        // this, or messages logged before this line won't retroactively appear in /logs. Also
        // switches the JVM's default console handler(s) to JSON-lines, matching router_py's
        // shared/json_log.py: same {ts, level, logger, message} shape on stdout and on /logs.
        Logger root = Logger.getLogger("");
        for (java.util.logging.Handler handler : root.getHandlers()) {
            handler.setFormatter(new JsonLogFormatter());
        }
        root.addHandler(logBuffer);

        this.server = HttpServer.create(new InetSocketAddress(bindHost, port), 0);
        registerBuiltinRoutes();
    }

    /** Returns null if authorized, or an error response body to write already-sent by this call. */
    private boolean checkAuth(HttpExchange exchange) throws IOException {
        if (authToken == null) {
            return true; // no-op check when authToken is unset
        }
        String token = exchange.getRequestHeaders().getFirst("X-Router-Auth");
        if (token == null || !token.equals(authToken)) {
            sendJson(exchange, 401, Map.of("error", "unauthorized"));
            return false;
        }
        return true;
    }

    private void registerBuiltinRoutes() {
        server.createContext("/stats", exchange -> {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            sendJson(exchange, 200, stats.snapshot());
        });

        server.createContext("/stop", exchange -> {
            if (!requireMethod(exchange, "GET", "POST")) {
                return;
            }
            if (!checkAuth(exchange)) {
                return;
            }
            stopEvent.set();
            sendJson(exchange, 200, Map.of("status", "stopping"));
        });

        server.createContext("/log_level", exchange -> {
            if (!requireMethod(exchange, "GET", "POST")) {
                return;
            }
            if ("POST".equals(exchange.getRequestMethod())) {
                if (!checkAuth(exchange)) {
                    return;
                }
                Map<?, ?> body = readJsonBody(exchange);
                String level = body != null && body.get("level") != null ? body.get("level").toString() : "INFO";
                Logger.getLogger("").setLevel(LogLevels.parse(level));
                sendJson(exchange, 200, Map.of("level", level.toUpperCase()));
            } else {
                Level current = Logger.getLogger("").getLevel();
                sendJson(exchange, 200, Map.of("level", LogLevels.toPythonName(current)));
            }
        });

        server.createContext("/logs", exchange -> {
            if (!requireMethod(exchange, "GET")) {
                return;
            }
            List<String> lines = logBuffer.getLines();
            String query = exchange.getRequestURI().getQuery();
            if (query != null && query.contains("format=text")) {
                // Each line is already a standalone JSON object (JSON-lines format) - fine to
                // ship/tail as-is without re-parsing.
                sendText(exchange, 200, String.join("\n", lines));
            } else {
                List<Object> parsed = new java.util.ArrayList<>(lines.size());
                for (String line : lines) {
                    try {
                        parsed.add(MAPPER.readValue(line, Map.class));
                    } catch (Exception e) {
                        parsed.add(Map.of("message", line));
                    }
                }
                sendJson(exchange, 200, parsed);
            }
        });
    }

    /**
     * Registers a custom route, mirroring router_py's {@code CommandServer.register(path, methods,
     * protected)} decorator: the handler is responsible for writing its own response, exactly
     * like the Python routes do, and this wrapper only enforces method + optional auth first.
     */
    public void register(String path, List<String> methods, boolean protectedRoute, HttpHandler handler) {
        server.createContext(path, exchange -> {
            if (!requireMethod(exchange, methods.toArray(new String[0]))) {
                return;
            }
            if (protectedRoute && !checkAuth(exchange)) {
                return;
            }
            handler.handle(exchange);
        });
    }

    private static boolean requireMethod(HttpExchange exchange, String... allowed) throws IOException {
        String method = exchange.getRequestMethod();
        for (String m : allowed) {
            if (m.equalsIgnoreCase(method)) {
                return true;
            }
        }
        sendText(exchange, 405, "Method Not Allowed");
        return false;
    }

    private static Map<?, ?> readJsonBody(HttpExchange exchange) throws IOException {
        byte[] body = exchange.getRequestBody().readAllBytes();
        if (body.length == 0) {
            return null;
        }
        return MAPPER.readValue(body, Map.class);
    }

    public static void sendJson(HttpExchange exchange, int status, Object body) throws IOException {
        byte[] payload = MAPPER.writeValueAsBytes(body);
        exchange.getResponseHeaders().add("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, payload.length);
        try (OutputStream os = exchange.getResponseBody()) {
            os.write(payload);
        }
    }

    public static void sendText(HttpExchange exchange, int status, String body) throws IOException {
        byte[] payload = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "text/plain");
        exchange.sendResponseHeaders(status, payload.length);
        try (OutputStream os = exchange.getResponseBody()) {
            os.write(payload);
        }
    }

    public static Map<?, ?> parseJsonBody(HttpExchange exchange) throws IOException {
        return readJsonBody(exchange);
    }

    public void start() {
        // Daemon threads for every request-handling thread, matching router_py's design intent - but
        // note this alone is NOT sufficient for the JVM to exit on its own: HttpServer's internal
        // dispatcher thread is not a daemon thread regardless of this executor's threads, so
        // every Main class explicitly calls System.exit() once its stop event is honored (see
        // RouterMain.main() / the simulators' main() methods) rather than relying on this.
        server.setExecutor(Executors.newCachedThreadPool(runnable -> {
            Thread t = new Thread(runnable);
            t.setDaemon(true);
            return t;
        }));
        server.start();
    }
}

package com.xv6;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.xv6.router.CryptoConfig;
import com.xv6.router.DownstreamConfig;
import com.xv6.router.RouterConfig;
import com.xv6.router.RouterMain;
import com.xv6.router.UpstreamConfig;
import com.xv6.shared.CommandServer;
import com.xv6.shared.Framing;
import com.xv6.shared.FramingConfig;
import com.xv6.shared.ImsConnect;
import com.xv6.shared.Stats;
import com.xv6.shared.StopEvent;
import com.xv6.simulators.cryptohost.CryptoHostMain;
import com.xv6.simulators.downstreamhost.DownstreamHostMain;
import com.xv6.simulators.upstreamhost.UpstreamHostMain;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.io.File;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Full-stack integration test: crypto_host/downstream_host/router/upstream_host wired together
 * in-process (each on its own thread/dedicated port), a CSV-equivalent set of requests uploaded
 * through the real HTTP command API, and field 39 asserted on the results. Direct Java analog of
 * xv5's tests/test_router.py.
 */
class RouterFullStackTest {

    private static final String PROJECT_ROOT = System.getProperty("user.dir");
    private static final String SPEC_PATH = PROJECT_ROOT + "/config/test_spec.xml";
    private static final String PANS_PATH = PROJECT_ROOT + "/config/pans_defined.json";

    private static final int CRYPTO_CMD = 18082;
    private static final int CRYPTO_REST = 18052;
    private static final int DS_CMD = 18081;
    private static final int DS_PORT = 18051;
    private static final int ROUTER_CMD = 18080;
    private static final int ROUTER_UPSTREAM_PORT = 18050;
    private static final int UPSTREAM_CMD = 18083;

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final HttpClient HTTP = HttpClient.newHttpClient();

    private static StopEvent routerStop;
    private static StopEvent cryptoStop;
    private static StopEvent downstreamStop;
    private static StopEvent upstreamStop;
    private static Path inputDir;

    @BeforeAll
    static void startStack() throws Exception {
        String pluginId = "test-plugin-id";
        String bearerToken = "test-bearer-token";

        Map<String, Object> cryptoCfg = new LinkedHashMap<>();
        cryptoCfg.put("port", CRYPTO_REST);
        cryptoCfg.put("command_port", CRYPTO_CMD);
        cryptoCfg.put("pans_defined", PANS_PATH);
        cryptoCfg.put("plugin_id", pluginId);
        cryptoCfg.put("bearer_token", bearerToken);
        CryptoHostMain crypto = new CryptoHostMain(cryptoCfg);
        cryptoStop = stopEventOf(crypto);
        crypto.start();

        Map<String, Object> dsCfg = new LinkedHashMap<>();
        dsCfg.put("port", DS_PORT);
        dsCfg.put("command_port", DS_CMD);
        dsCfg.put("iso_spec", SPEC_PATH);
        dsCfg.put("pans_defined", PANS_PATH);
        DownstreamHostMain downstream = new DownstreamHostMain(dsCfg);
        downstreamStop = stopEventOf(downstream);
        downstream.start();

        waitReady(CRYPTO_CMD, null);
        waitReady(DS_CMD, null);

        FramingConfig framing = new FramingConfig("", "ASCII", 4, Framing.DEFAULT_MAX_MESSAGE_BYTES);
        RouterConfig routerCfg = new RouterConfig(
                "test_router", ROUTER_CMD,
                new UpstreamConfig(ROUTER_UPSTREAM_PORT, framing, "server", "localhost", 5),
                new DownstreamConfig("localhost", DS_PORT, ImsConnect.toEbcdic("IRM_ID01", 8), ImsConnect.toEbcdic("CLIENT01", 8)),
                new CryptoConfig("localhost", CRYPTO_REST, pluginId, bearerToken),
                SPEC_PATH, null, "DEBUG", 8, 10, 40, 1000, 30, 5, 30, 2.0, "127.0.0.1", null);
        routerStop = new StopEvent();
        Thread routerThread = new Thread(() -> {
            try {
                RouterMain.run(routerCfg, routerStop, new Stats(routerCfg.yellowThresholdSeconds()));
            } catch (Exception e) {
                throw new RuntimeException(e);
            }
        }, "router-main");
        routerThread.setDaemon(true);
        routerThread.start();
        waitReady(ROUTER_CMD, null);

        inputDir = Files.createTempDirectory("upstream_1_input");
        Map<String, Object> upstreamCfg = new LinkedHashMap<>();
        upstreamCfg.put("command_port", UPSTREAM_CMD);
        upstreamCfg.put("router", Map.of("host", "localhost", "port", ROUTER_UPSTREAM_PORT));
        upstreamCfg.put("framing", Map.of("header_hex", "", "length_field_type", "ASCII", "length_field_bytes", 4));
        upstreamCfg.put("iso_spec", SPEC_PATH);
        upstreamCfg.put("input_dir", inputDir.toString());
        upstreamCfg.put("ping_0800_seconds", 3600);
        UpstreamHostMain upstream = new UpstreamHostMain(upstreamCfg);
        upstreamStop = stopEventOf(upstream);
        upstream.start();

        waitReady(UPSTREAM_CMD, "router");
        waitReady(ROUTER_CMD, "downstream");
    }

    @AfterAll
    static void stopStack() {
        if (routerStop != null) {
            routerStop.set();
        }
        if (cryptoStop != null) {
            cryptoStop.set();
        }
        if (downstreamStop != null) {
            downstreamStop.set();
        }
        if (upstreamStop != null) {
            upstreamStop.set();
        }
    }

    private static StopEvent stopEventOf(Object sim) throws Exception {
        java.lang.reflect.Field f = sim.getClass().getDeclaredField("stopEvent");
        f.setAccessible(true);
        return (StopEvent) f.get(sim);
    }

    private static Map<String, Object> getJson(int port, String path) throws Exception {
        HttpRequest req = HttpRequest.newBuilder().uri(URI.create("http://127.0.0.1:" + port + path)).GET().build();
        HttpResponse<String> resp = HTTP.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() != 200) {
            throw new IOException("HTTP " + resp.statusCode());
        }
        return MAPPER.readValue(resp.body(), Map.class);
    }

    @SuppressWarnings("unchecked")
    private static void waitReady(int port, String connectionKey) throws Exception {
        long deadline = System.currentTimeMillis() + 10_000;
        while (System.currentTimeMillis() < deadline) {
            try {
                Map<String, Object> data = getJson(port, "/stats");
                if (connectionKey == null) {
                    return;
                }
                Map<String, Object> connections = (Map<String, Object>) data.get("connections");
                if (connections != null && Boolean.TRUE.equals(connections.get(connectionKey))) {
                    return;
                }
            } catch (Exception ignored) {
            }
            Thread.sleep(200);
        }
        throw new IllegalStateException("port " + port + " not ready (key=" + connectionKey + ")");
    }

    @Test
    void fullStackAuthorization() throws Exception {
        Path csvPath = inputDir.resolve("test_cases.csv");
        Files.writeString(csvPath, String.join("\n",
                "2;3;4;11;expected_39",
                "4111111111111111;000000;000000000100;000001;00",
                "9999999999999999;000000;000000000200;000002;01") + "\n");

        HttpRequest startReq = HttpRequest.newBuilder()
                .uri(URI.create("http://127.0.0.1:" + UPSTREAM_CMD + "/start")).GET().build();
        HttpResponse<String> startResp = HTTP.send(startReq, HttpResponse.BodyHandlers.ofString());
        assertEquals(200, startResp.statusCode());
        Map<String, Object> startBody = MAPPER.readValue(startResp.body(), Map.class);
        assertEquals(2, ((Number) startBody.get("rows")).intValue());

        long deadline = System.currentTimeMillis() + 10_000;
        List<Map<String, Object>> results = List.of();
        while (System.currentTimeMillis() < deadline) {
            HttpRequest resultsReq = HttpRequest.newBuilder()
                    .uri(URI.create("http://127.0.0.1:" + UPSTREAM_CMD + "/results")).GET().build();
            HttpResponse<String> resultsResp = HTTP.send(resultsReq, HttpResponse.BodyHandlers.ofString());
            results = MAPPER.readValue(resultsResp.body(), List.class);
            if (results.size() >= 2) {
                break;
            }
            Thread.sleep(300);
        }

        assertEquals(2, results.size());
        Map<String, Map<String, Object>> byPan = new LinkedHashMap<>();
        for (Map<String, Object> r : results) {
            byPan.put(String.valueOf(r.get("2")), r);
        }
        assertEquals("00", byPan.get("4111111111111111").get("resp_39"));
        assertTrue(byPan.get("4111111111111111").get("resp_38") != null
                && !String.valueOf(byPan.get("4111111111111111").get("resp_38")).isEmpty());
        assertEquals("01", byPan.get("9999999999999999").get("resp_39"));
    }
}

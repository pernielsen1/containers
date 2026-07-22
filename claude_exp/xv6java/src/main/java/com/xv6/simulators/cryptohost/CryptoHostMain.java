package com.xv6.simulators.cryptohost;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import com.xv6.shared.CommandServer;
import com.xv6.shared.CryptoUtils;
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
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.logging.Logger;

/** Stateless HTTP service for cryptographic validation. Port of xv5's
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
        this.cmd = new CommandServer((Integer) cfg.get("command_port"), stats, stopEvent, "127.0.0.1", null);
    }

    @SuppressWarnings("unchecked")
    private String validate(String pan, String f47Str) {
        Map<String, Object> data = IsoUtils.f47Decode(f47Str);

        Map<String, String> panInfo = pans.get(pan);
        if (panInfo == null) {
            data.put("response_code", "14");
            return IsoUtils.f47Encode(data);
        }

        String rc = "00";

        if (data.containsKey("f52")) {
            if (!CryptoUtils.verifyPin(pan, String.valueOf(data.get("f52")), panInfo.get("pek"), panInfo.get("pin"))) {
                rc = "55";
            }
        }

        Map<String, Object> f55 = (Map<String, Object>) data.get("f55");
        Object messageType = data.get("message_type");

        if (f55 != null && "0100".equals(messageType) && "00".equals(rc)) {
            if (!CryptoUtils.verifyArqc(pan, panInfo.get("pan_seq"), panInfo.get("imk_ac"), f55)) {
                rc = "82";
            }
        }

        if (f55 != null && "0110".equals(messageType)) {
            String udk = CryptoUtils.deriveUdk(panInfo.get("imk_ac"), pan, panInfo.get("pan_seq"));
            String sk = CryptoUtils.deriveSessionKey(udk, String.valueOf(f55.getOrDefault("atc", "0000")));
            String arcHex = HexFormat.of().formatHex(rc.getBytes(StandardCharsets.US_ASCII));
            byte[] arpc = CryptoUtils.calculateArpcMethod1(
                    String.valueOf(f55.getOrDefault("cryptogram", "0000000000000000")), arcHex, sk);
            f55.put("arpc", Base64.getEncoder().encodeToString(arpc));
        }

        if (data.containsKey("cvv2") && "00".equals(rc)) {
            String f14 = String.valueOf(data.getOrDefault("f14", ""));
            if (!CryptoUtils.verifyCvv2(pan, f14, String.valueOf(data.get("cvv2")), panInfo.get("cvk"))) {
                rc = "N7";
            }
        }

        if (data.containsKey("aav") && "00".equals(rc)) {
            if (!CryptoUtils.verifyAav(data, panInfo.get("aav_key"), pan)) {
                rc = "82";
            }
        }

        data.put("response_code", rc);
        return IsoUtils.f47Encode(data);
    }

    @SuppressWarnings("unchecked")
    private void registerValidateRoute(HttpServer server, String path) {
        server.createContext(path, exchange -> {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                CommandServer.sendText(exchange, 405, "Method Not Allowed");
                return;
            }
            stats.recordRecv();
            Map<String, Object> body = MAPPER.readValue(exchange.getRequestBody().readAllBytes(), Map.class);
            String pan = String.valueOf(body.getOrDefault("f2", ""));
            String f47 = String.valueOf(body.getOrDefault("f47", ""));
            String result = validate(pan, f47);
            stats.recordSent();
            CommandServer.sendJson(exchange, 200, Map.of("f47", result));
        });
    }

    public void start() throws IOException {
        cmd.start();

        HttpServer validateServer = HttpServer.create(new InetSocketAddress("127.0.0.1", (Integer) cfg.get("port")), 0);
        registerValidateRoute(validateServer, "/validate_0100");
        registerValidateRoute(validateServer, "/validate_0110");
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
            // left), so unlike xv5 (where every thread genuinely is a daemon thread and the
            // interpreter exits on its own), this JVM needs an explicit exit once the stop event
            // has been honored.
            System.exit(0);
        } catch (Exception e) {
            e.printStackTrace();
            System.exit(1);
        }
    }
}

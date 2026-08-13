package com.xv6.router;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.xv6.shared.SslUtils;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Base64;
import java.util.Map;
import java.util.logging.Level;
import java.util.logging.Logger;

/** Fortanix-shaped crypto client: POST /sys/v1/plugins/{plugin_id}, bearer auth, base64 response.
 * Wired this way so swapping in a real Fortanix DSM tenant is a config/URL change, not a rewrite. */
public class CryptoClient {

    private static final Logger logger = Logger.getLogger(CryptoClient.class.getName());
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final String baseUrl;
    private final String bearerToken;
    private final HttpClient client;
    private final int breakerThreshold;
    private final int breakerCooldownSeconds;
    private final Object lock = new Object();
    private int failureCount = 0;
    private long openUntilMillis = 0;

    public CryptoClient(CryptoConfig cfg, int breakerThreshold, int breakerCooldownSeconds) throws IOException {
        String scheme = cfg.ssl_active() ? "https" : "http";
        this.baseUrl = scheme + "://" + cfg.host() + ":" + cfg.port() + "/sys/v1/plugins/" + cfg.plugin_id();
        this.bearerToken = cfg.bearer_token();
        HttpClient.Builder builder = HttpClient.newBuilder();
        if (cfg.ssl_active()) {
            builder.sslContext(SslUtils.buildClientContext(cfg.certfile(), cfg.keyfile(), cfg.cafile()));
        }
        this.client = builder.build();
        this.breakerThreshold = breakerThreshold;
        this.breakerCooldownSeconds = breakerCooldownSeconds;
    }

    /**
     * Returns the enriched f47 on success, or "" on any failure (breaker open or HTTP error) -
     * callers only overwrite their working f47 when this return value is non-empty, so any
     * failure path leaves the original f47 untouched. Handles Fortanix PluginOutput envelope:
     * response body is a JSON string literal (base64 "format":"byte"), which we decode to reach
     * the inner {"f47": ...} object.
     *
     * routerStan isn't part of the Fortanix plugin contract - it's passed through so crypto_host's
     * own logs can be joined with this router's logs on the same transaction (mirrors router_py's
     * crypto_client.py). Empty string when a caller has none.
     */
    public String validate(String endpoint, String pan, String f47, String routerStan) {
        synchronized (lock) {
            if (System.currentTimeMillis() < openUntilMillis) {
                return "";
            }
        }

        try {
            String json = MAPPER.writeValueAsString(
                    Map.of("operation", endpoint, "f2", pan, "f47", f47, "router_stan", routerStan));
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl))
                    .timeout(Duration.ofSeconds(5))
                    .header("Content-Type", "application/json")
                    .header("Authorization", "Bearer " + bearerToken)
                    .POST(HttpRequest.BodyPublishers.ofString(json))
                    .build();
            HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() >= 400) {
                throw new IOException("HTTP " + response.statusCode());
            }

            String body = response.body();
            if (body == null || body.isEmpty()) {
                throw new IOException("empty response body");
            }

            String base64String = MAPPER.readValue(body, String.class);
            String decodedJson = new String(Base64.getDecoder().decode(base64String), StandardCharsets.UTF_8);
            Map<?, ?> parsed = MAPPER.readValue(decodedJson, Map.class);
            Object result = parsed.get("f47");

            synchronized (lock) {
                failureCount = 0;
            }
            return result == null ? "" : result.toString();
        } catch (Exception e) {
            logger.log(Level.WARNING, "crypto_host " + endpoint + " call failed (router_stan=" + routerStan
                    + "): " + e.getMessage());
            synchronized (lock) {
                failureCount++;
                if (failureCount >= breakerThreshold) {
                    openUntilMillis = System.currentTimeMillis() + breakerCooldownSeconds * 1000L;
                    logger.warning("crypto breaker open for " + breakerCooldownSeconds
                            + "s after " + failureCount + " consecutive failures");
                }
            }
            return "";
        }
    }
}

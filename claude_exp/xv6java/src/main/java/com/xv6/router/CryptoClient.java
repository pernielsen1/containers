package com.xv6.router;

import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;
import java.util.logging.Level;
import java.util.logging.Logger;

/** Port of xv5's router/crypto_client.py. {@link HttpClient} is thread-safe, like Python's
 * requests.Session(), so one instance is shared across dispatcher worker threads. */
public class CryptoClient {

    private static final Logger logger = Logger.getLogger(CryptoClient.class.getName());
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final String baseUrl;
    private final HttpClient client = HttpClient.newHttpClient();
    private final int breakerThreshold;
    private final int breakerCooldownSeconds;
    private final Object lock = new Object();
    private int failureCount = 0;
    private long openUntilMillis = 0;

    public CryptoClient(CryptoConfig cfg, int breakerThreshold, int breakerCooldownSeconds) {
        this.baseUrl = "http://" + cfg.host() + ":" + cfg.port();
        this.breakerThreshold = breakerThreshold;
        this.breakerCooldownSeconds = breakerCooldownSeconds;
    }

    /**
     * Returns the enriched f47 on success, or "" on any failure (breaker open or HTTP error) -
     * callers only overwrite their working f47 when this return value is non-empty, so any
     * failure path leaves the original f47 untouched.
     */
    public String validate(String endpoint, String pan, String f47) {
        synchronized (lock) {
            if (System.currentTimeMillis() < openUntilMillis) {
                return "";
            }
        }

        try {
            String json = MAPPER.writeValueAsString(Map.of("f2", pan, "f47", f47));
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + "/" + endpoint))
                    .timeout(Duration.ofSeconds(5))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(json))
                    .build();
            HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() >= 400) {
                throw new IOException("HTTP " + response.statusCode());
            }
            Map<?, ?> parsed = MAPPER.readValue(response.body(), Map.class);
            Object result = parsed.get("f47");

            synchronized (lock) {
                failureCount = 0;
            }
            return result == null ? "" : result.toString();
        } catch (Exception e) {
            logger.log(Level.WARNING, "crypto_host " + endpoint + " call failed: " + e.getMessage());
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

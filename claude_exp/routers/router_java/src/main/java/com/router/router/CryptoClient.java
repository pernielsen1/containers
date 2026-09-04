package com.router.router;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.router.shared.LogThrottle;
import com.router.shared.SslUtils;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Base64;
import java.util.Map;
import java.util.concurrent.Semaphore;
import java.util.logging.Level;
import java.util.logging.Logger;

/** Fortanix-shaped crypto client: POST /sys/v1/plugins/{plugin_id}, bearer auth, base64 response.
 * Wired this way so swapping in a real Fortanix DSM tenant is a config/URL change, not a rewrite. */
public class CryptoClient {

    private static final Logger logger = Logger.getLogger(CryptoClient.class.getName());
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final LogThrottle throttledLog = new LogThrottle(logger, 200);

    private final String baseUrl;
    private final String bearerToken;
    private final int breakerThreshold;
    private final int breakerCooldownSeconds;
    private final long idleTimeoutMillis;
    private final Object lock = new Object();
    private int failureCount = 0;
    private long openUntilMillis = 0;
    // Bumped every time the breaker opens (and in resetBreaker()) - see validate()'s failure
    // branch. A thread's cached client is only trusted if it was built under the *current*
    // generation; ThreadLocal means one thread can't reach into another thread's cached client to
    // discard it directly when crypto_host dies, so instead every thread checks its own client's
    // generation the next time it needs one and discards it on mismatch, before ever trying to use
    // it - see getClient(). Never retried inline (see sendRequest()): a failed call is forgotten,
    // not rescued, on the theory that recovering *this* transaction isn't the goal - having a
    // fresh client ready for the next one is. Mirrors router_py's crypto_client.py _generation.
    private int generation = 0;

    // One HttpClient/SSLContext per dispatcher worker thread rather than one shared instance -
    // see build_router.md's CryptoClient section: a single HttpClient driven to open several
    // brand-new mTLS connections concurrently from different threads hits a genuine
    // java.net.http.HttpClient concurrency bug (intermittent "fatal alert: internal_error" on
    // ~1-2 of every 8 concurrent first-use connections, reproduced in isolation outside this
    // router entirely). Giving each thread its own fully independent client eliminated it in the
    // same isolated test - confirmed the shared instance, not crypto_host, was at fault.
    //
    // Bundled with its generation and last-used time into one CachedClient object rather than
    // three loose ThreadLocal fields kept in sync by hand - same idiom router_py's
    // crypto_client.py (_CachedConnection) and upstream_host/main.py (_Connection) use for the
    // analogous "a cached resource can go stale" problem. See getClient()/forgetClient().
    private final ThreadLocal<CachedClient> clientTL = new ThreadLocal<>();
    private final CryptoConfig cfg;

    private static final class CachedClient {
        final HttpClient client;
        final int generation;
        long lastUsedMillis;

        CachedClient(HttpClient client, int generation, long lastUsedMillis) {
            this.client = client;
            this.generation = generation;
            this.lastUsedMillis = lastUsedMillis;
        }
    }

    // Even fully independent HttpClient instances aren't safe to *construct and first-use*
    // concurrently (same isolated test: sequential construction, then concurrent use -> 0
    // failures; concurrent construction -> the same alert again, shared SSLContext or not). This
    // gate serializes only that one-time moment per thread (see warmup()) without blocking
    // Dispatcher.start() itself - an earlier attempt that made start() launch worker threads one
    // at a time (waiting on each thread's own warm-up before starting the next) fixed the alert
    // but delayed the router's upstream-accept readiness by ~(workerThreads +
    // responseWorkerThreads) * ~1-1.5s, long enough to blow past stress_run.sh's own connect
    // timeout - self-serializing here instead lets start() return immediately as before.
    private final Semaphore warmupGate = new Semaphore(1);

    public CryptoClient(CryptoConfig cfg, int breakerThreshold, int breakerCooldownSeconds) throws IOException {
        this(cfg, breakerThreshold, breakerCooldownSeconds, 4.0);
    }

    /** idleTimeoutSeconds: a thread's cached client is proactively discarded once idle past this
     * long (default 4.0s, under crypto_host's own ~5s keep-alive idle timeout) - separate from the
     * generation check above: a client can go stale from an ordinary traffic lull alone, with no
     * breaker event at all. Reproduced directly (router_py side, same shared crypto_host): after
     * any ~5s+ gap in traffic, the next reuse of an idle cached connection fails on both the
     * request and response legs - same "anticipate staleness, don't discover it by failing first"
     * principle as the generation check, just against a timer instead of an event. Mirrors
     * router_py's crypto_client.py idle_timeout_seconds. */
    public CryptoClient(CryptoConfig cfg, int breakerThreshold, int breakerCooldownSeconds,
            double idleTimeoutSeconds) throws IOException {
        String scheme = cfg.ssl_active() ? "https" : "http";
        this.baseUrl = scheme + "://" + cfg.host() + ":" + cfg.port() + "/sys/v1/plugins/" + cfg.plugin_id();
        this.bearerToken = cfg.bearer_token();
        this.breakerThreshold = breakerThreshold;
        this.breakerCooldownSeconds = breakerCooldownSeconds;
        this.idleTimeoutMillis = Math.round(idleTimeoutSeconds * 1000.0);
        this.cfg = cfg;

        if (cfg.ssl_active()) {
            // Fail fast on a bad cert/key/ca path here, at startup - otherwise this would only
            // surface on a worker thread's first real validate() call, indistinguishable from an
            // ordinary crypto_host failure instead of a startup misconfiguration.
            SslUtils.buildClientContext(cfg.certfile(), cfg.keyfile(), cfg.cafile());
        }
    }

    /** Returns this thread's cached client, discarding and rebuilding it first if it was built
     * under a stale generation or has sat idle too long - mirrors router_py's
     * crypto_client.py _get_connection(). */
    private HttpClient getClient() {
        int currentGeneration;
        synchronized (lock) {
            currentGeneration = generation;
        }
        long now = System.currentTimeMillis();
        CachedClient cached = clientTL.get();
        if (cached != null) {
            boolean idleTooLong = (now - cached.lastUsedMillis) > idleTimeoutMillis;
            if (cached.generation != currentGeneration || idleTooLong) {
                closeQuietly(cached.client);
                cached = null;
            }
        }
        if (cached == null) {
            cached = new CachedClient(buildClient(cfg), currentGeneration, now);
            clientTL.set(cached);
        } else {
            cached.lastUsedMillis = now;
        }
        return cached.client;
    }

    /** Discards this thread's cached client outright - called after a genuine transport failure
     * (see sendRequest()) so the next call, this thread's or another's, starts from a known-fresh
     * client instead of inheriting a guessing game. Mirrors _forget_connection(). */
    private void forgetClient() {
        CachedClient cached = clientTL.get();
        if (cached != null) {
            closeQuietly(cached.client);
        }
        clientTL.remove();
    }

    private static void closeQuietly(HttpClient client) {
        try {
            client.close();
        } catch (Exception e) {
            // best-effort - being discarded either way
        }
    }

    /** Sends one request over this thread's cached client, forgetting (closing + discarding) that
     * client on any transport-level failure - never retried inline (see class-level generation
     * doc). Deliberately does NOT forget the client on an HTTP-level error status (>=400, checked
     * by the caller after this returns) - a bad status over a working connection isn't evidence
     * the connection itself is broken. Mirrors _send(). */
    private HttpResponse<String> sendRequest(HttpRequest request) throws IOException, InterruptedException {
        HttpClient client = getClient();
        try {
            return client.send(request, HttpResponse.BodyHandlers.ofString());
        } catch (IOException | InterruptedException e) {
            forgetClient();
            throw e;
        }
    }

    private static HttpClient buildClient(CryptoConfig cfg) {
        HttpClient.Builder builder = HttpClient.newBuilder();
        if (cfg.ssl_active()) {
            try {
                builder.sslContext(SslUtils.buildClientContext(cfg.certfile(), cfg.keyfile(), cfg.cafile()));
            } catch (IOException e) {
                // Already validated once in the constructor - a failure here means the cert files
                // changed or became unreadable after startup, not a config typo.
                throw new UncheckedIOException(e);
            }
        }
        return builder.build();
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
    private static final Duration REQUEST_TIMEOUT = Duration.ofSeconds(5);
    // Cold JVM TLS start (KeyManagerFactory/TrustManagerFactory class-loading and JIT, cipher
    // negotiation) has been measured up to ~4.6s in isolation on an idle host, and observed
    // exceeding the standard 5s REQUEST_TIMEOUT outright on this host under real load (every
    // worker/response-worker thread's first-ever call, serialized through warmupGate, hitting
    // "HTTP connect timed out" back to back) - a longer timeout only for that one-time first call
    // gives it enough room without loosening the 5s deadline real (already-warm) traffic is held
    // to, where a slow crypto_host is a genuine problem worth detecting quickly.
    private static final Duration WARMUP_TIMEOUT = Duration.ofSeconds(20);

    /** Returns the enriched f47 on success (possibly "" if crypto_host genuinely had nothing to
     * add), or null on any genuine failure (breaker open or HTTP error) - mirrors router_py's
     * crypto_client.py (None vs "") and router_cpp's CryptoClient (std::nullopt vs ""). A caller
     * that only needs "fail open" (the request leg) can keep treating both null and "" as "don't
     * overwrite"; a caller that must distinguish "no-op success" from "genuine failure" (the
     * response leg, which needs to drop rather than forward unvalidated) must check for null
     * specifically, not just isEmpty(). */
    public String validate(String endpoint, String pan, String f47, String routerStan) {
        return validate(endpoint, pan, f47, routerStan, REQUEST_TIMEOUT);
    }

    private String validate(String endpoint, String pan, String f47, String routerStan, Duration timeout) {
        synchronized (lock) {
            if (System.currentTimeMillis() < openUntilMillis) {
                return null;
            }
        }

        try {
            String json = MAPPER.writeValueAsString(
                    Map.of("operation", endpoint, "f2", pan, "f47", f47, "router_stan", routerStan));
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl))
                    .timeout(timeout)
                    .header("Content-Type", "application/json")
                    .header("Authorization", "Bearer " + bearerToken)
                    .POST(HttpRequest.BodyPublishers.ofString(json))
                    .build();
            HttpResponse<String> response = sendRequest(request);
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
            throttledLog.log(Level.WARNING, "crypto_call_failed:" + endpoint,
                    "crypto_host " + endpoint + " call failed (router_stan=" + routerStan
                            + "): " + e.getMessage());
            synchronized (lock) {
                failureCount++;
                if (failureCount >= breakerThreshold) {
                    openUntilMillis = System.currentTimeMillis() + breakerCooldownSeconds * 1000L;
                    generation++;
                    logger.warning("crypto breaker open for " + breakerCooldownSeconds
                            + "s after " + failureCount + " consecutive failures");
                }
            }
            return null;
        }
    }

    /** Closes the breaker immediately rather than waiting for its own cooldown clock to expire and
     * self-renew (see validate()'s failure branch, which re-arms openUntilMillis on every failed
     * post-cooldown probe with no awareness of whether the service actually recovered) - for a
     * caller that has *externally confirmed* the service is back (e.g. a TCP probe against its
     * port) and wants the breaker to trust that immediately instead of on its own delayed
     * schedule. Bumps generation like a normal open/close cycle so every thread's cached client is
     * rebuilt fresh, matching a real recovery. Mirrors router_py's crypto_client.py
     * reset_breaker(). */
    public void resetBreaker() {
        synchronized (lock) {
            failureCount = 0;
            openUntilMillis = 0;
            generation++;
        }
    }

    /** Forces the calling thread's own HttpClient/SSLContext (see clientTL above) through its
     * one-time cold-start cost (KeyManagerFactory/TrustManagerFactory class-loading and JIT,
     * cipher-suite negotiation) here, synchronously, before that thread starts handling real
     * traffic. Measured in isolation at ~0.5-1.5s on this host for the client build, then another
     * ~1-2s for the first request. Must be called once from each dispatcher worker/response-worker
     * thread itself (see Dispatcher.workerLoop/responseWorkerLoop) - calling it from any other
     * thread only warms that other thread's own ThreadLocal client, not the worker's.
     * {@code warmupGate} serializes this specific call across threads (see its own doc) so no two
     * threads' client construction/first-use ever overlaps, without blocking anything else. The
     * call's own success/failure isn't reported to the caller - even a failed warm-up call has
     * already paid the cold-start cost for whatever comes next on this thread. */
    public void warmup() {
        try {
            warmupGate.acquire();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return;
        }
        try {
            validate("validate_0100", "0", "", "warmup", WARMUP_TIMEOUT);
        } finally {
            warmupGate.release();
        }
    }
}

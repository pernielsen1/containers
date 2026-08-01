package com.xv6.router;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/**
 * Raw JSON shape of a router config.json, deserialized directly by Jackson.
 * {@code @JsonIgnoreProperties(ignoreUnknown = true)} is what makes router_py's RouterConfig.from_file
 * "exclusion set" bug class (build_router_v2.md's documented pitfall: every JSON key consumed
 * elsewhere, or monitor-only metadata like "type"/"is_active", had to be added to a manually
 * maintained tuple or startup crashed with TypeError) disappear by construction here - unknown
 * keys are silently ignored instead.
 *
 * Defaults for fields commonly omitted from config.json live in the compact constructor, which
 * Jackson's record support still runs on every deserialization (a compact constructor is the
 * same canonical constructor Jackson invokes reflectively, just with implicit field assignment
 * after the body) - this is what replaces Python's dataclass field defaults. 0 is used as the
 * "not set" sentinel for the int fields below since none of them is ever a meaningful real value
 * of 0 in this system (a 0-length queue, 0-second TTL, etc. would be nonsensical); reconnectJitterSeconds
 * uses a boxed Double instead, since 0.0 jitter is a legitimate configured value someone might
 * deliberately choose, unlike the others.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record RouterConfigJson(
        String name,
        int commandPort,
        UpstreamConfig upstream,
        DownstreamConfigJson downstream,
        CryptoConfig crypto,
        String isoSpec,
        String upstreamIsoEncoding,
        String partnerId,
        String logLevel,
        int workerThreads,
        int responseWorkerThreads,
        int reestablishSeconds,
        int yellowThresholdSeconds,
        int queueMaxsize,
        int pendingTtlSeconds,
        int cryptoBreakerThreshold,
        int cryptoBreakerCooldownSeconds,
        Double reconnectJitterSeconds,
        String commandBindHost,
        String commandAuthToken) {

    public RouterConfigJson {
        if (logLevel == null) {
            logLevel = "INFO";
        }
        if (workerThreads == 0) {
            workerThreads = 8;
        }
        if (responseWorkerThreads == 0) {
            responseWorkerThreads = 8;
        }
        if (reestablishSeconds == 0) {
            reestablishSeconds = 10;
        }
        if (yellowThresholdSeconds == 0) {
            yellowThresholdSeconds = 40;
        }
        if (queueMaxsize == 0) {
            queueMaxsize = 1000;
        }
        if (pendingTtlSeconds == 0) {
            pendingTtlSeconds = 30;
        }
        if (cryptoBreakerThreshold == 0) {
            cryptoBreakerThreshold = 5;
        }
        if (cryptoBreakerCooldownSeconds == 0) {
            cryptoBreakerCooldownSeconds = 30;
        }
        if (reconnectJitterSeconds == null) {
            reconnectJitterSeconds = 2.0;
        }
        if (commandBindHost == null) {
            commandBindHost = "127.0.0.1";
        }
        // partnerId, commandAuthToken: null is the correct Python default already (both are
        // Optional[str] = None in the dataclass).
    }
}

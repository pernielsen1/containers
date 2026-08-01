package com.xv6.router;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;

import java.io.File;
import java.io.IOException;
import java.nio.file.Path;

/**
 * Resolved router configuration: same fields as {@link RouterConfigJson}, but with
 * {@code isoSpec} resolved to an absolute path (relative to the config file's directory, like
 * router_py's from_file) and {@code downstream} converted to its EBCDIC-ready form. Port of router_py's
 * router/config.py RouterConfig dataclass.
 */
public record RouterConfig(
        String name,
        int commandPort,
        UpstreamConfig upstream,
        DownstreamConfig downstream,
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
        double reconnectJitterSeconds,
        String commandBindHost,
        String commandAuthToken) {

    private static final ObjectMapper MAPPER =
            new ObjectMapper().setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);

    public static RouterConfig fromFile(String path) throws IOException {
        RouterConfigJson raw = MAPPER.readValue(new File(path), RouterConfigJson.class);
        String baseDir = new File(path).getAbsoluteFile().getParent();
        String resolvedIsoSpec = Path.of(baseDir).resolve(raw.isoSpec()).normalize().toString();

        return new RouterConfig(
                raw.name(),
                raw.commandPort(),
                raw.upstream(),
                DownstreamConfig.from(raw.downstream()),
                raw.crypto(),
                resolvedIsoSpec,
                raw.upstreamIsoEncoding(),
                raw.partnerId(),
                raw.logLevel(),
                raw.workerThreads(),
                raw.responseWorkerThreads(),
                raw.reestablishSeconds(),
                raw.yellowThresholdSeconds(),
                raw.queueMaxsize(),
                raw.pendingTtlSeconds(),
                raw.cryptoBreakerThreshold(),
                raw.cryptoBreakerCooldownSeconds(),
                raw.reconnectJitterSeconds(),
                raw.commandBindHost(),
                raw.commandAuthToken());
    }
}

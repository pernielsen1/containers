package com.xv6.router;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.xv6.shared.FramingConfig;

/** Port of xv5's router/config.py UpstreamConfig dataclass. Deserialized directly by Jackson. */
@JsonIgnoreProperties(ignoreUnknown = true)
public record UpstreamConfig(
        int port,
        FramingConfig framing,
        String mode,
        String host,
        int retrySeconds) {

    public UpstreamConfig {
        if (mode == null) {
            mode = "server";
        }
        if (host == null) {
            host = "localhost";
        }
        if (retrySeconds == 0) {
            retrySeconds = 5;
        }
    }
}

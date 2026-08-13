package com.xv6.router;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/** Fortanix-shaped crypto service config: POST /sys/v1/plugins/{plugin_id} with bearer auth. */
@JsonIgnoreProperties(ignoreUnknown = true)
public record CryptoConfig(
        String host, int port, String plugin_id, String bearer_token,
        boolean ssl_active, String certfile, String keyfile, String cafile) {
}

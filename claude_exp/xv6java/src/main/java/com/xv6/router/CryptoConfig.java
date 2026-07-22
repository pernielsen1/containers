package com.xv6.router;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/** Port of xv5's router/config.py CryptoConfig dataclass. */
@JsonIgnoreProperties(ignoreUnknown = true)
public record CryptoConfig(String host, int port) {
}

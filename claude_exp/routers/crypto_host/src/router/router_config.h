#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "shared/framing.h"

namespace xv6::router {

struct UpstreamConfig {
    std::string mode = "server";  // "server" | "client"
    std::string host = "localhost";
    int port = 0;
    int command_port = 8083;  // upstream_host simulator's own CommandServer port
    int retry_seconds = 5;
    int ping_0800_seconds = 30;
    xv6::shared::FramingConfig framing;
};

struct DownstreamConfig {
    std::string host;
    int port = 0;
    int command_port = 8081;  // downstream_host simulator's own CommandServer port
    std::vector<uint8_t> irm_id;     // EBCDIC-encoded, exactly 8 bytes
    std::vector<uint8_t> client_id;  // EBCDIC-encoded, exactly 8 bytes
};

struct CryptoConfig {
    std::string host;
    int port = 0;              // crypto_host's /sys/v1/plugins/{plugin_id} business route port
    int command_port = 8082;   // crypto_host simulator's own CommandServer port
    std::string plugin_id;
    std::string bearer_token;

    bool ssl_active = false;
    std::string certfile;
    std::string keyfile;
    std::string cafile;
};

struct RouterConfig {
    std::string name;
    std::optional<std::string> partner_id;
    std::string log_level = "INFO";
    int command_port = 8080;
    std::string command_bind_host = "127.0.0.1";
    std::optional<std::string> command_auth_token;

    // Resolved to an absolute/relative-to-cwd path in from_file() -- the "pans_defined" JSON key
    // is relative to the config file's own directory, matching how the config's own path is given
    // on the command line.
    std::string pans_defined_path = "pans_defined.json";

    UpstreamConfig upstream;
    DownstreamConfig downstream;
    CryptoConfig crypto;

    int worker_threads = 8;
    int reestablish_seconds = 10;
    int yellow_threshold_seconds = 40;
    int queue_maxsize = 1000;
    int pending_ttl_seconds = 30;
    int crypto_breaker_threshold = 5;
    int crypto_breaker_cooldown_seconds = 30;
    double reconnect_jitter_seconds = 2.0;

    // Loads the JSON config, resolving `downstream.irm_id`/`client_id` to 8-byte EBCDIC.
    // Unrecognized JSON keys (type, is_active, monitor-only metadata) are silently ignored --
    // this function only ever reads the keys it knows about.
    static RouterConfig from_file(const std::string& path);
};

}  // namespace xv6::router

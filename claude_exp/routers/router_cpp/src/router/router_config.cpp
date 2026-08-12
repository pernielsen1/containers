#include "router/router_config.h"

#include <filesystem>
#include <fstream>
#include <stdexcept>

#include <nlohmann/json.hpp>

#include "shared/ebcdic.h"

namespace xv6::router {

namespace {

// Empty stays empty (ssl_active defaults to false, so an absent path is legitimate); otherwise
// resolved relative to the config file's own directory, matching pans_defined_path below.
std::string resolve_path(const std::filesystem::path& base_dir, const std::string& value) {
    if (value.empty()) return value;
    std::filesystem::path p(value);
    if (p.is_relative()) p = base_dir / p;
    return p.string();
}

xv6::shared::FramingConfig parse_framing(const nlohmann::json& j) {
    xv6::shared::FramingConfig cfg;
    cfg.header_hex = j.value("header_hex", std::string(""));
    cfg.length_field_type =
        xv6::shared::parse_length_field_type(j.value("length_field_type", std::string("ASCII")));
    cfg.length_field_bytes = j.value("length_field_bytes", 4);
    cfg.max_message_bytes = j.value("max_message_bytes", 65536);
    return cfg;
}

UpstreamConfig parse_upstream(const nlohmann::json& j, const std::filesystem::path& base_dir) {
    UpstreamConfig cfg;
    cfg.mode = j.value("mode", std::string("server"));
    cfg.host = j.value("host", std::string("localhost"));
    cfg.port = j.value("port", 0);
    cfg.command_port = j.value("command_port", 8083);
    cfg.retry_seconds = j.value("retry_seconds", 5);
    cfg.ping_0800_seconds = j.value("ping_0800_seconds", 30);
    cfg.encoding = j.value("encoding", std::string("ascii"));
    if (j.contains("framing")) {
        cfg.framing = parse_framing(j.at("framing"));
    }
    cfg.ssl_active = j.value("ssl_active", false);
    cfg.certfile = resolve_path(base_dir, j.value("certfile", std::string("")));
    cfg.keyfile = resolve_path(base_dir, j.value("keyfile", std::string("")));
    cfg.cafile = resolve_path(base_dir, j.value("cafile", std::string("")));
    return cfg;
}

DownstreamConfig parse_downstream(const nlohmann::json& j, const std::filesystem::path& base_dir) {
    DownstreamConfig cfg;
    cfg.host = j.value("host", std::string(""));
    cfg.port = j.value("port", 0);
    cfg.command_port = j.value("command_port", 8081);
    cfg.irm_id = xv6::shared::to_ebcdic(j.value("irm_id", std::string("")), 8);
    cfg.client_id = xv6::shared::to_ebcdic(j.value("client_id", std::string("")), 8);
    cfg.ssl_active = j.value("ssl_active", false);
    cfg.certfile = resolve_path(base_dir, j.value("certfile", std::string("")));
    cfg.keyfile = resolve_path(base_dir, j.value("keyfile", std::string("")));
    cfg.cafile = resolve_path(base_dir, j.value("cafile", std::string("")));
    return cfg;
}

CryptoConfig parse_crypto(const nlohmann::json& j, const std::filesystem::path& base_dir) {
    CryptoConfig cfg;
    cfg.host = j.value("host", std::string(""));
    cfg.port = j.value("port", 0);
    cfg.command_port = j.value("command_port", 8082);
    cfg.plugin_id = j.value("plugin_id", std::string(""));
    cfg.bearer_token = j.value("bearer_token", std::string(""));
    cfg.ssl_active = j.value("ssl_active", false);
    cfg.certfile = resolve_path(base_dir, j.value("certfile", std::string("")));
    cfg.keyfile = resolve_path(base_dir, j.value("keyfile", std::string("")));
    cfg.cafile = resolve_path(base_dir, j.value("cafile", std::string("")));
    return cfg;
}

}  // namespace

RouterConfig RouterConfig::from_file(const std::string& path) {
    std::ifstream in(path);
    if (!in) {
        throw std::runtime_error("failed to open router config: " + path);
    }
    nlohmann::json j;
    in >> j;
    std::filesystem::path base_dir = std::filesystem::path(path).parent_path();

    RouterConfig cfg;
    cfg.name = j.value("name", std::string(""));
    if (j.contains("partner_id") && !j.at("partner_id").is_null()) {
        cfg.partner_id = j.at("partner_id").get<std::string>();
    }
    cfg.log_level = j.value("log_level", std::string("INFO"));
    cfg.command_port = j.value("command_port", 8080);
    cfg.command_bind_host = j.value("command_bind_host", std::string("127.0.0.1"));
    if (j.contains("command_auth_token") && !j.at("command_auth_token").is_null()) {
        cfg.command_auth_token = j.at("command_auth_token").get<std::string>();
    }

    if (j.contains("upstream")) cfg.upstream = parse_upstream(j.at("upstream"), base_dir);
    if (j.contains("downstream")) cfg.downstream = parse_downstream(j.at("downstream"), base_dir);
    if (j.contains("crypto")) cfg.crypto = parse_crypto(j.at("crypto"), base_dir);

    cfg.worker_threads = j.value("worker_threads", 8);
    cfg.response_worker_threads = j.value("response_worker_threads", 8);
    cfg.reestablish_seconds = j.value("reestablish_seconds", 10);
    cfg.yellow_threshold_seconds = j.value("yellow_threshold_seconds", 40);
    cfg.queue_maxsize = j.value("queue_maxsize", 1000);
    cfg.pending_ttl_seconds = j.value("pending_ttl_seconds", 30);
    cfg.crypto_breaker_threshold = j.value("crypto_breaker_threshold", 5);
    cfg.crypto_breaker_cooldown_seconds = j.value("crypto_breaker_cooldown_seconds", 30);
    cfg.reconnect_jitter_seconds = j.value("reconnect_jitter_seconds", 2.0);

    std::string pans_defined = j.value("pans_defined", std::string("pans_defined.json"));
    std::filesystem::path pans_path(pans_defined);
    if (pans_path.is_relative()) {
        pans_path = std::filesystem::path(path).parent_path() / pans_path;
    }
    cfg.pans_defined_path = pans_path.string();

    return cfg;
}

}  // namespace xv6::router

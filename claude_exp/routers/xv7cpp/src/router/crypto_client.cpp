#include "router/crypto_client.h"

#include <nlohmann/json.hpp>

#include "shared/base64.h"
#include "shared/log.h"

namespace xv6::router {

CryptoClient::CryptoClient(const CryptoConfig& cfg, int breaker_threshold, int breaker_cooldown_seconds)
    : cfg_(cfg),
      base_path_("/sys/v1/plugins/" + cfg.plugin_id),
      client_(cfg.host, cfg.port),
      breaker_threshold_(breaker_threshold),
      breaker_cooldown_seconds_(breaker_cooldown_seconds) {
    client_.set_connection_timeout(5, 0);
    client_.set_read_timeout(5, 0);
    client_.set_write_timeout(5, 0);
}

void CryptoClient::record_failure() {
    std::lock_guard<std::mutex> lock(breaker_mutex_);
    ++failure_count_;
    if (failure_count_ >= breaker_threshold_) {
        open_until_ = std::chrono::steady_clock::now() + std::chrono::seconds(breaker_cooldown_seconds_);
    }
}

void CryptoClient::reset_failure() {
    std::lock_guard<std::mutex> lock(breaker_mutex_);
    failure_count_ = 0;
}

std::string CryptoClient::validate(const std::string& endpoint, const std::string& pan, const std::string& f47) {
    {
        std::lock_guard<std::mutex> lock(breaker_mutex_);
        if (std::chrono::steady_clock::now() < open_until_) {
            return "";
        }
    }

    nlohmann::json body = {{"operation", endpoint}, {"f2", pan}, {"f47", f47}};
    httplib::Headers headers = {{"Authorization", "Bearer " + cfg_.bearer_token}};

    auto res = client_.Post(base_path_, headers, body.dump(), "application/json");
    if (!res || res->status >= 400) {
        LOG_WARNING("crypto_client: " + endpoint + " request failed, status=" +
                    (res ? std::to_string(res->status) : std::string("(no response)")));
        record_failure();
        return "";
    }

    try {
        // The 2XX body is a JSON string literal -- the PluginOutput envelope (base64,
        // "format": "byte"), not a JSON object wrapping it.
        std::string base64_str = nlohmann::json::parse(res->body).get<std::string>();
        auto decoded_bytes = xv6::shared::base64_decode(base64_str);
        std::string decoded_json(decoded_bytes.begin(), decoded_bytes.end());
        auto inner = nlohmann::json::parse(decoded_json);
        std::string f47_out = inner.value("f47", std::string(""));
        reset_failure();
        return f47_out;
    } catch (const std::exception& e) {
        LOG_WARNING(std::string("crypto_client: failed to decode PluginOutput envelope: ") + e.what());
        record_failure();
        return "";
    }
}

}  // namespace xv6::router

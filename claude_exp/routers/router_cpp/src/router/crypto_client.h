#pragma once

#include <chrono>
#include <memory>
#include <mutex>
#include <string>

#include <httplib.h>

#include "router/router_config.h"

namespace router {

// HTTP client to crypto_host with a circuit breaker. Wire interface deliberately mimics
// Fortanix DSM's "invoke a plugin execution" API (POST /sys/v1/plugins/{plugin_id}, bearer-token
// auth, base64 PluginOutput response) so a later swap to a real Fortanix DSM tenant is a
// config/URL change, not a rewrite of this class.
class CryptoClient {
public:
    CryptoClient(const CryptoConfig& cfg, int breaker_threshold, int breaker_cooldown_seconds);

    // endpoint is "validate_0100" or "validate_0110". Returns the enriched f47 JSON string on
    // success, or "" on any failure (breaker open, HTTP error, bad auth, unknown plugin_id,
    // malformed response) -- callers must only overwrite their working f47 when this is
    // non-empty, so a down/misconfigured crypto host degrades to "checks silently skipped."
    //
    // router_stan isn't part of the Fortanix plugin contract - it's passed through so
    // crypto_host's own logs can be joined with this router's logs on the same transaction
    // (mirrors router_py's crypto_client.py / router_java's CryptoClient.java). Empty string
    // when a caller has none.
    std::string validate(const std::string& endpoint, const std::string& pan, const std::string& f47,
                          const std::string& router_stan = "");

private:
    void record_failure();
    void reset_failure();
    // Builds a freshly-configured client (connection/read/write timeouts applied) - used to
    // lazily construct each worker thread's own thread_local httplib::Client the first time it
    // calls validate(), since httplib::Client isn't safe to share across concurrent threads.
    httplib::Client make_client() const;

    CryptoConfig cfg_;
    std::string base_path_;

    int breaker_threshold_;
    int breaker_cooldown_seconds_;
    std::mutex breaker_mutex_;
    int failure_count_ = 0;
    std::chrono::steady_clock::time_point open_until_{};
};

}  // namespace router

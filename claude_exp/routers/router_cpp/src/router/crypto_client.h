#pragma once

#include <chrono>
#include <memory>
#include <mutex>
#include <optional>
#include <string>

#include <httplib.h>

#include "router/router_config.h"
#include "shared/log_throttle.h"

namespace router {

// HTTP client to crypto_host with a circuit breaker. Wire interface deliberately mimics
// Fortanix DSM's "invoke a plugin execution" API (POST /sys/v1/plugins/{plugin_id}, bearer-token
// auth, base64 PluginOutput response) so a later swap to a real Fortanix DSM tenant is a
// config/URL change, not a rewrite of this class.
class CryptoClient {
public:
    CryptoClient(const CryptoConfig& cfg, int breaker_threshold, int breaker_cooldown_seconds,
                 double idle_timeout_seconds = 4.0);

    // endpoint is "validate_0100" or "validate_0110". Returns the enriched f47 JSON string on
    // success (possibly "" if crypto_host genuinely had nothing to add), or std::nullopt on any
    // genuine failure (breaker open, HTTP error, bad auth, unknown plugin_id, malformed response)
    // -- mirrors router_py's crypto_client.py (None vs "") and router_java's CryptoClient.java
    // (null vs ""). A caller that only needs "fail open" (the request leg) can keep treating both
    // nullopt and "" as "don't overwrite"; a caller that must distinguish "no-op success" from
    // "genuine failure" (the response leg, which needs to drop rather than forward unvalidated)
    // must check has_value() specifically, not just emptiness.
    //
    // router_stan isn't part of the Fortanix plugin contract - it's passed through so
    // crypto_host's own logs can be joined with this router's logs on the same transaction
    // (mirrors router_py's crypto_client.py / router_java's CryptoClient.java). Empty string
    // when a caller has none.
    std::optional<std::string> validate(const std::string& endpoint, const std::string& pan, const std::string& f47,
                                         const std::string& router_stan = "");

    // Closes the breaker immediately rather than waiting out its own cooldown clock, and bumps
    // generation_ the same way a normal open/close cycle does so every thread's cached client is
    // rebuilt fresh - for a caller that has *externally confirmed* crypto_host is back (e.g. a
    // real port probe) and doesn't want to wait on this client's own delayed schedule. Mirrors
    // router_py's crypto_client.py CryptoClient.reset_breaker().
    void reset_breaker();

private:
    void record_failure();
    void reset_failure();
    // Builds a freshly-configured client (connection/read/write timeouts applied) - used to
    // lazily construct each worker thread's own thread_local httplib::Client the first time it
    // calls validate(), since httplib::Client isn't safe to share across concurrent threads.
    httplib::Client make_client() const;
    // Current generation under breaker_mutex_ - read once per validate() call before touching
    // this thread's cached client (see the CachedClient struct in crypto_client.cpp).
    int generation();

    CryptoConfig cfg_;
    std::string base_path_;

    int breaker_threshold_;
    int breaker_cooldown_seconds_;
    double idle_timeout_seconds_;
    std::mutex breaker_mutex_;
    int failure_count_ = 0;
    std::chrono::steady_clock::time_point open_until_{};
    // Bumped whenever the breaker opens (record_failure()) or is force-closed (reset_breaker()).
    // A thread's cached client is only reused if it was built under the *current* generation -
    // thread_local storage means one thread can't reach into another thread's cached client to
    // close it directly when crypto_host dies, so instead every thread checks its own client's
    // generation the next time it needs one and discards it on mismatch, before ever trying to
    // use it (see validate()). Mirrors router_py's crypto_client.py _generation.
    int generation_ = 0;
    shared::LogThrottle throttle_{200};
};

}  // namespace router

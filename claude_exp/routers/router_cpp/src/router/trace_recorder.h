#pragma once

#include <cstdint>
#include <deque>
#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include <nlohmann/json.hpp>

namespace xv6::router {

// On-demand, self-expiring capture of full per-hop transaction detail for live diagnosis at
// production volume - briefs/debug_trace_master.md Phase 4. Off by default: the hot path pays
// only a lock + map-lookup per hop call site when disarmed (no wire-byte hex-encoding, no extra
// allocation), so it's safe to leave wired in permanently rather than only under a feature flag.
// Once armed via arm(), captures the next `count` transactions - optionally filtered to a
// specific upstream_stan or pan - end to end: raw wire bytes at every hop plus per-hop elapsed
// time, then auto-disarms so a capture can never accidentally run forever. Port of router_py's
// router/trace.py / router_java's TraceRecorder.java. Entries are nlohmann::json objects (not a
// fixed struct like PendingSnapshotEntry) because a hop's extra fields genuinely vary by stage
// (wire_hex for the byte-carrying hops, crypto_ms/enriched for crypto_call) - matching the
// dict/Map<String,Object> shape used by the Python/Java ports.
class TraceRecorder {
public:
    explicit TraceRecorder(size_t max_entries = 50);

    void arm(int count, const std::string& stan = "", const std::string& pan = "");

    // Called once per transaction, at its first hop. Returns whether this transaction is being
    // traced, so callers can skip building later hop details (e.g. re-encoding bytes that would
    // otherwise just be discarded) when it isn't.
    bool start(const std::string& router_stan, const std::string& upstream_stan, const std::string& pan,
               const std::string& mti, const std::vector<uint8_t>& raw);

    bool is_tracing(const std::string& router_stan);

    void hop(const std::string& router_stan, const std::string& stage, const std::vector<uint8_t>* raw = nullptr,
              const nlohmann::json& extra_fields = nlohmann::json::object());

    void finish(const std::string& router_stan);

    // Flushes any traces that were mid-capture into entries (marked incomplete) instead of
    // leaking them silently - called from Dispatcher::drain_and_stop() so a session teardown
    // mid-trace doesn't just vanish, same reasoning as the pending-transaction abandonment log
    // added there.
    std::vector<nlohmann::json> abandon_in_progress();

    nlohmann::json snapshot();

private:
    void add_entry(nlohmann::json entry);

    std::mutex mutex_;
    size_t max_entries_;
    bool armed_ = false;
    int remaining_ = 0;
    std::optional<std::string> filter_stan_;
    std::optional<std::string> filter_pan_;
    std::deque<nlohmann::json> entries_;
    std::unordered_map<std::string, nlohmann::json> in_progress_;  // holds "_started_at_ns" (int64_t)
};

}  // namespace xv6::router

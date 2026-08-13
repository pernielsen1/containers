#pragma once

#include <deque>
#include <map>
#include <mutex>
#include <optional>
#include <string>

#include <nlohmann/json.hpp>

namespace shared {

// Thread-safe rolling counters. Windows {30, 60, 180, 1800} seconds, backed by one mutex and
// two deques of send/recv timestamps (millis), trimmed to the max window on every record.
class Stats {
public:
    explicit Stats(std::optional<int> yellow_threshold_seconds);

    void set_connection(const std::string& name, bool connected);
    void set_gauge(const std::string& name, nlohmann::json value);
    void record_sent();
    void record_recv();

    // Records one timing sample under a named bucket (e.g. "queue_wait", "crypto_rtt",
    // "downstream_rtt", "total" - see Dispatcher) for live per-hop latency visibility in
    // /stats, without waiting on an offline soak-test CSV. Available on every actor type
    // (Stats is shared), not just the router - any actor with a hop worth timing can call this
    // the same way. Bounded by count (kLatencyMaxLen), not time, same "keep last N" convention
    // as LogBuffer. Matches router_py's shared/stats.py / router_java's Stats.recordLatency().
    void record_latency(const std::string& name, double value_ms);

    // keys: sent_total, recv_total, sent_30s/recv_30s ... sent_1800s/recv_1800s,
    // seconds_since_last_recv (double|null), last_recv_datetime (HH:MM:SS|null),
    // yellow_threshold_seconds (only if set), connections (object, only if non-empty),
    // gauges (object, only if non-empty), latency (object, only if non-empty - per-bucket
    // count/min_ms/p50_ms/p95_ms/max_ms)
    nlohmann::json snapshot() const;

private:
    static constexpr size_t kLatencyMaxLen = 2000;

    void trim(std::deque<int64_t>& dq, int64_t now_ms) const;
    int count_within(const std::deque<int64_t>& dq, int64_t now_ms, int window_seconds) const;

    mutable std::mutex mutex_;
    std::deque<int64_t> sent_ts_;
    std::deque<int64_t> recv_ts_;
    uint64_t sent_total_ = 0;
    uint64_t recv_total_ = 0;
    std::optional<int64_t> last_recv_ms_;
    std::map<std::string, bool> connections_;
    std::map<std::string, nlohmann::json> gauges_;
    std::map<std::string, std::deque<double>> latencies_;
    std::optional<int> yellow_threshold_seconds_;
};

}  // namespace shared

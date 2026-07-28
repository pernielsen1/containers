#pragma once

#include <deque>
#include <map>
#include <mutex>
#include <optional>
#include <string>

#include <nlohmann/json.hpp>

namespace xv6::shared {

// Thread-safe rolling counters. Windows {30, 60, 180, 1800} seconds, backed by one mutex and
// two deques of send/recv timestamps (millis), trimmed to the max window on every record.
class Stats {
public:
    explicit Stats(std::optional<int> yellow_threshold_seconds);

    void set_connection(const std::string& name, bool connected);
    void set_gauge(const std::string& name, nlohmann::json value);
    void record_sent();
    void record_recv();

    // keys: sent_total, recv_total, sent_30s/recv_30s ... sent_1800s/recv_1800s,
    // seconds_since_last_recv (double|null), last_recv_datetime (HH:MM:SS|null),
    // yellow_threshold_seconds (only if set), connections (object, only if non-empty),
    // gauges (object, only if non-empty)
    nlohmann::json snapshot() const;

private:
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
    std::optional<int> yellow_threshold_seconds_;
};

}  // namespace xv6::shared

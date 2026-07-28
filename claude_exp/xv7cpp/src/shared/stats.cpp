#include "shared/stats.h"

#include <array>
#include <chrono>
#include <cmath>
#include <ctime>

namespace xv6::shared {

namespace {

constexpr std::array<int, 4> kWindows = {30, 60, 180, 1800};
constexpr int kMaxWindowSeconds = 1800;

int64_t now_ms() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
               std::chrono::system_clock::now().time_since_epoch())
        .count();
}

}  // namespace

Stats::Stats(std::optional<int> yellow_threshold_seconds)
    : yellow_threshold_seconds_(yellow_threshold_seconds) {}

void Stats::set_connection(const std::string& name, bool connected) {
    std::lock_guard<std::mutex> lock(mutex_);
    connections_[name] = connected;
}

void Stats::set_gauge(const std::string& name, nlohmann::json value) {
    std::lock_guard<std::mutex> lock(mutex_);
    gauges_[name] = std::move(value);
}

void Stats::record_sent() {
    std::lock_guard<std::mutex> lock(mutex_);
    int64_t t = now_ms();
    sent_ts_.push_back(t);
    ++sent_total_;
    trim(sent_ts_, t);
}

void Stats::record_recv() {
    std::lock_guard<std::mutex> lock(mutex_);
    int64_t t = now_ms();
    recv_ts_.push_back(t);
    ++recv_total_;
    last_recv_ms_ = t;
    trim(recv_ts_, t);
}

void Stats::trim(std::deque<int64_t>& dq, int64_t now_ms_val) const {
    int64_t cutoff = now_ms_val - static_cast<int64_t>(kMaxWindowSeconds) * 1000;
    while (!dq.empty() && dq.front() < cutoff) {
        dq.pop_front();
    }
}

int Stats::count_within(const std::deque<int64_t>& dq, int64_t now_ms_val, int window_seconds) const {
    int64_t cutoff = now_ms_val - static_cast<int64_t>(window_seconds) * 1000;
    int count = 0;
    for (auto it = dq.rbegin(); it != dq.rend(); ++it) {
        if (*it >= cutoff) {
            ++count;
        } else {
            break;
        }
    }
    return count;
}

nlohmann::json Stats::snapshot() const {
    std::lock_guard<std::mutex> lock(mutex_);
    int64_t t = now_ms();

    nlohmann::json out;
    out["sent_total"] = sent_total_;
    out["recv_total"] = recv_total_;
    for (int w : kWindows) {
        out["sent_" + std::to_string(w) + "s"] = count_within(sent_ts_, t, w);
        out["recv_" + std::to_string(w) + "s"] = count_within(recv_ts_, t, w);
    }

    if (last_recv_ms_.has_value()) {
        double secs = static_cast<double>(t - *last_recv_ms_) / 1000.0;
        secs = std::round(secs * 10.0) / 10.0;
        out["seconds_since_last_recv"] = secs;

        std::time_t tt = static_cast<std::time_t>(*last_recv_ms_ / 1000);
        std::tm tm_buf{};
        localtime_r(&tt, &tm_buf);
        char buf[16];
        std::strftime(buf, sizeof(buf), "%H:%M:%S", &tm_buf);
        out["last_recv_datetime"] = std::string(buf);
    } else {
        out["seconds_since_last_recv"] = nullptr;
        out["last_recv_datetime"] = nullptr;
    }

    if (yellow_threshold_seconds_.has_value()) {
        out["yellow_threshold_seconds"] = *yellow_threshold_seconds_;
    }
    if (!connections_.empty()) {
        nlohmann::json conns = nlohmann::json::object();
        for (const auto& [k, v] : connections_) {
            conns[k] = v;
        }
        out["connections"] = std::move(conns);
    }
    if (!gauges_.empty()) {
        nlohmann::json g = nlohmann::json::object();
        for (const auto& [k, v] : gauges_) {
            g[k] = v;
        }
        out["gauges"] = std::move(g);
    }
    return out;
}

}  // namespace xv6::shared

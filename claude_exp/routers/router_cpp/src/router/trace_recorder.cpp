#include "router/trace_recorder.h"

#include <algorithm>
#include <chrono>
#include <cmath>

namespace xv6::router {

namespace {

std::string to_hex(const std::vector<uint8_t>& raw) {
    static const char* digits = "0123456789abcdef";
    std::string out;
    out.reserve(raw.size() * 2);
    for (uint8_t b : raw) {
        out.push_back(digits[b >> 4]);
        out.push_back(digits[b & 0x0f]);
    }
    return out;
}

int64_t now_ns() {
    return std::chrono::steady_clock::now().time_since_epoch().count();
}

double round3(double v) { return std::round(v * 1000.0) / 1000.0; }

}  // namespace

TraceRecorder::TraceRecorder(size_t max_entries) : max_entries_(max_entries) {}

void TraceRecorder::arm(int count, const std::string& stan, const std::string& pan) {
    std::lock_guard<std::mutex> lock(mutex_);
    remaining_ = std::max(count, 0);
    armed_ = remaining_ > 0;
    filter_stan_ = stan.empty() ? std::nullopt : std::optional<std::string>(stan);
    filter_pan_ = pan.empty() ? std::nullopt : std::optional<std::string>(pan);
}

bool TraceRecorder::start(const std::string& router_stan, const std::string& upstream_stan,
                           const std::string& pan, const std::string& mti, const std::vector<uint8_t>& raw) {
    if (!armed_) {
        return false;
    }
    std::lock_guard<std::mutex> lock(mutex_);
    if (!armed_) {
        return false;
    }
    if (filter_stan_ && *filter_stan_ != upstream_stan) {
        return false;
    }
    if (filter_pan_ && *filter_pan_ != pan) {
        return false;
    }
    remaining_ -= 1;
    if (remaining_ <= 0) {
        armed_ = false;
    }

    nlohmann::json entry = {
        {"router_stan", router_stan},
        {"upstream_stan", upstream_stan},
        {"pan", pan},
        {"mti", mti},
        {"_started_at_ns", now_ns()},
        {"hops", nlohmann::json::array({{{"stage", "upstream_recv"}, {"elapsed_ms", 0.0}, {"wire_hex", to_hex(raw)}}})},
    };
    in_progress_[router_stan] = std::move(entry);
    return true;
}

bool TraceRecorder::is_tracing(const std::string& router_stan) {
    std::lock_guard<std::mutex> lock(mutex_);
    return in_progress_.find(router_stan) != in_progress_.end();
}

void TraceRecorder::hop(const std::string& router_stan, const std::string& stage, const std::vector<uint8_t>* raw,
                          const nlohmann::json& extra_fields) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = in_progress_.find(router_stan);
    if (it == in_progress_.end()) {
        return;
    }
    int64_t started_at_ns = it->second.at("_started_at_ns").get<int64_t>();
    double elapsed_ms = (now_ns() - started_at_ns) / 1'000'000.0;

    nlohmann::json record = {{"stage", stage}, {"elapsed_ms", round3(elapsed_ms)}};
    if (raw != nullptr) {
        record["wire_hex"] = to_hex(*raw);
    }
    if (extra_fields.is_object()) {
        for (auto& [key, value] : extra_fields.items()) {
            record[key] = value;
        }
    }
    it->second["hops"].push_back(std::move(record));
}

void TraceRecorder::finish(const std::string& router_stan) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = in_progress_.find(router_stan);
    if (it == in_progress_.end()) {
        return;
    }
    nlohmann::json entry = std::move(it->second);
    entry.erase("_started_at_ns");
    in_progress_.erase(it);
    add_entry(std::move(entry));
}

std::vector<nlohmann::json> TraceRecorder::abandon_in_progress() {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<nlohmann::json> abandoned;
    abandoned.reserve(in_progress_.size());
    for (auto& [stan, entry] : in_progress_) {
        entry["incomplete"] = true;
        entry.erase("_started_at_ns");
        abandoned.push_back(entry);
        add_entry(entry);
    }
    in_progress_.clear();
    return abandoned;
}

nlohmann::json TraceRecorder::snapshot() {
    std::lock_guard<std::mutex> lock(mutex_);
    nlohmann::json entries = nlohmann::json::array();
    for (const auto& e : entries_) {
        entries.push_back(e);
    }
    return {{"armed", armed_}, {"remaining", remaining_}, {"entries", entries}};
}

void TraceRecorder::add_entry(nlohmann::json entry) {
    entries_.push_back(std::move(entry));
    while (entries_.size() > max_entries_) {
        entries_.pop_front();
    }
}

}  // namespace xv6::router

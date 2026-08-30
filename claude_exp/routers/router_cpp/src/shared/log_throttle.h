#pragma once

#include <mutex>
#include <string>
#include <unordered_map>

#include "shared/log.h"

namespace shared {

// Wraps Logger for conditions that can fire once per transaction (crypto_host call failures,
// dropped 0110s) - briefs/resilience_v2.md's fail_percentage/crypto-kill chaos scenarios turn a
// rare warning into a sustained per-transaction flood without this (mirrors router_py's
// shared/log_throttle.py::ThrottledLogger 1:1).
//
// Logs the first occurrence of a condition in full, then only every `every`-th repeat after that
// (with a running count appended) - so the condition is never silent, but volume drops by ~`every`x.
// Counts are per key, not per call site, so unrelated conditions throttle independently.
class LogThrottle {
public:
    explicit LogThrottle(int every = 200) : every_(every) {}

    void log(LogLevel level, const std::string& key, const std::string& msg) {
        uint64_t count;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            count = ++counts_[key];
        }
        if (count == 1) {
            Logger::instance().log(level, msg);
        } else if (count % static_cast<uint64_t>(every_) == 0) {
            Logger::instance().log(
                level, msg + " [occurrence #" + std::to_string(count) + " of this condition, throttled]");
        }
    }

private:
    int every_;
    std::mutex mutex_;
    std::unordered_map<std::string, uint64_t> counts_;
};

}  // namespace shared

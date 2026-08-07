#include "shared/log.h"

#include <algorithm>
#include <chrono>
#include <cctype>
#include <cstdio>
#include <ctime>
#include <iostream>

#include <nlohmann/json.hpp>

namespace xv6::shared {

namespace {

std::string to_upper(const std::string& s) {
    std::string out = s;
    std::transform(out.begin(), out.end(), out.begin(), [](unsigned char c) { return std::toupper(c); });
    return out;
}

// Matches the shape (and roughly the precision) of router_py's JsonFormatter
// (shared/json_log.py) - not the same field set (no "logger" name here, this Logger is
// process-wide not per-module), but "ts"/"level"/"message" line up so /logs output from either
// side greps and jq's the same way.
std::string iso8601_utc_now() {
    auto now = std::chrono::system_clock::now();
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()) % 1000;
    std::time_t tt = std::chrono::system_clock::to_time_t(now);
    std::tm tm_buf{};
    gmtime_r(&tt, &tm_buf);
    char time_buf[32];
    std::strftime(time_buf, sizeof(time_buf), "%Y-%m-%dT%H:%M:%S", &tm_buf);
    char full_buf[40];
    std::snprintf(full_buf, sizeof(full_buf), "%s.%03dZ", time_buf, static_cast<int>(ms.count()));
    return std::string(full_buf);
}

}  // namespace

std::optional<LogLevel> parse_log_level(const std::string& name) {
    std::string upper = to_upper(name);
    if (upper == "DEBUG") return LogLevel::Debug;
    if (upper == "INFO") return LogLevel::Info;
    if (upper == "WARNING" || upper == "WARN") return LogLevel::Warning;
    if (upper == "ERROR") return LogLevel::Error;
    return std::nullopt;
}

std::string to_string(LogLevel level) {
    switch (level) {
        case LogLevel::Debug: return "DEBUG";
        case LogLevel::Info: return "INFO";
        case LogLevel::Warning: return "WARNING";
        case LogLevel::Error: return "ERROR";
    }
    return "INFO";
}

Logger& Logger::instance() {
    static Logger logger;
    return logger;
}

void Logger::set_level(LogLevel level) { level_.store(level); }

LogLevel Logger::level() const { return level_.load(); }

void Logger::log(LogLevel level, const std::string& msg) {
    if (static_cast<int>(level) < static_cast<int>(level_.load())) {
        return;
    }

    nlohmann::json entry = {
        {"ts", iso8601_utc_now()},
        {"level", to_string(level)},
        {"message", msg},
    };
    std::string line = entry.dump();

    {
        std::lock_guard<std::mutex> lock(mutex_);
        ring_.push_back(line);
        while (ring_.size() > kMaxLines) {
            ring_.pop_front();
        }
    }

    std::cerr << line << std::endl;
}

std::vector<std::string> Logger::buffered_lines() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return std::vector<std::string>(ring_.begin(), ring_.end());
}

}  // namespace xv6::shared

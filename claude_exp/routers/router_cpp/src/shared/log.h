#pragma once

#include <atomic>
#include <deque>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace xv6::shared {

enum class LogLevel { Debug, Info, Warning, Error };

std::optional<LogLevel> parse_log_level(const std::string& name);  // "DEBUG"/"INFO"/"WARNING"/"ERROR"
std::string to_string(LogLevel level);

// Process-wide logger: a level threshold plus a bounded in-memory ring buffer of formatted
// lines, exposed to CommandServer's /logs route.
class Logger {
public:
    static Logger& instance();

    void set_level(LogLevel level);
    LogLevel level() const;
    void log(LogLevel level, const std::string& msg);
    std::vector<std::string> buffered_lines() const;

private:
    Logger() = default;

    static constexpr size_t kMaxLines = 2000;

    mutable std::mutex mutex_;
    std::atomic<LogLevel> level_{LogLevel::Info};
    std::deque<std::string> ring_;
};

}  // namespace xv6::shared

#define LOG_DEBUG(msg) ::xv6::shared::Logger::instance().log(::xv6::shared::LogLevel::Debug, (msg))
#define LOG_INFO(msg) ::xv6::shared::Logger::instance().log(::xv6::shared::LogLevel::Info, (msg))
#define LOG_WARNING(msg) ::xv6::shared::Logger::instance().log(::xv6::shared::LogLevel::Warning, (msg))
#define LOG_ERROR(msg) ::xv6::shared::Logger::instance().log(::xv6::shared::LogLevel::Error, (msg))

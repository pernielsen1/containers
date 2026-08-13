#pragma once

#include <sys/socket.h>

#include <functional>
#include <memory>
#include <mutex>
#include <optional>

#include "router/router_config.h"

namespace router {

struct UpstreamConn {
    int fd = -1;
    sockaddr_storage addr{};
    std::shared_ptr<std::mutex> write_lock;
};

// should_stop is the combined "stop OR reconnect" predicate -- the caller (RouterSession)
// passes [&]{ return stop_event.is_set() || reconnect_event.is_set(); } so a single
// accept/connect loop can be woken by either condition without either API needing to know
// about both.
class UpstreamServer {
public:
    explicit UpstreamServer(const UpstreamConfig& cfg);
    ~UpstreamServer();
    UpstreamServer(const UpstreamServer&) = delete;
    UpstreamServer& operator=(const UpstreamServer&) = delete;

    // Loops on poll()/accept() with a 1s timeout, rechecking should_stop each iteration.
    // Returns nullopt on stop or a hard error.
    std::optional<UpstreamConn> accept(const std::function<bool()>& should_stop);

private:
    UpstreamConfig cfg_;
    int listen_fd_ = -1;
};

class UpstreamClient {
public:
    explicit UpstreamClient(UpstreamConfig cfg);

    // Connects to cfg.host:cfg.port (5s connect timeout); on failure, waits cfg.retry_seconds
    // (polling should_stop every 200ms) before retrying. Returns nullopt if should_stop becomes
    // true while waiting.
    std::optional<UpstreamConn> connect(const std::function<bool()>& should_stop);

private:
    bool wait_retry(const std::function<bool()>& should_stop) const;

    UpstreamConfig cfg_;
};

}  // namespace router

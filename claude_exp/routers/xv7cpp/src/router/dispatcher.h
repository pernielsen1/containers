#pragma once

#include <sys/socket.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#include "router/crypto_client.h"
#include "router/downstream_connection.h"
#include "router/router_config.h"
#include "shared/stats.h"
#include "shared/stop_event.h"

namespace xv6::router {

struct PendingEntry {
    int up_fd = -1;
    std::shared_ptr<std::mutex> up_write_lock;
    std::string upstream_stan;
    std::chrono::steady_clock::time_point created_at;
};

struct RoutedMessage {
    std::map<std::string, std::string> req;
    int up_fd = -1;
    std::shared_ptr<std::mutex> up_write_lock;
    sockaddr_storage addr{};
};

// Worker pool + STAN rewrite + pending map. Direct 1:1 port of the Java concurrency model --
// single mutex-guarded map, linear-scan reaper, no sharding. Routes 0100 upstream -> crypto ->
// downstream. Routes 0110/0130/0430 downstream -> upstream (via STAN lookup).
class Dispatcher {
public:
    Dispatcher(const RouterConfig& cfg, DownstreamConnection& downstream, CryptoClient& crypto,
               xv6::shared::Stats& stats, xv6::shared::StopEvent& reconnect_event);
    ~Dispatcher();
    Dispatcher(const Dispatcher&) = delete;
    Dispatcher& operator=(const Dispatcher&) = delete;

    // Spawns cfg.worker_threads worker threads running worker_loop(), plus one pending-reaper
    // thread.
    void start();

    void submit(RoutedMessage msg);                                          // blocking enqueue (backpressure)
    void handle_response(const std::map<std::string, std::string>& resp);      // called from the ds-receiver thread
    std::map<std::string, int> purge();                                        // operator drain; returns dropped counts
    void drain_and_stop();                                                     // poison-pill sentinels + join

private:
    void worker_loop();
    void reaper_loop();
    void process(RoutedMessage& msg);
    std::string next_stan();

    const RouterConfig& cfg_;
    DownstreamConnection& downstream_;
    CryptoClient& crypto_;
    xv6::shared::Stats& stats_;
    xv6::shared::StopEvent& reconnect_event_;

    std::deque<std::optional<RoutedMessage>> queue_;  // nullopt = poison pill
    std::mutex queue_mutex_;
    std::condition_variable queue_cv_not_full_;
    std::condition_variable queue_cv_not_empty_;

    std::unordered_map<std::string, PendingEntry> pending_;
    std::mutex pending_mutex_;

    std::atomic<int> stan_counter_{0};

    std::vector<std::thread> workers_;
    std::thread reaper_;
    xv6::shared::StopEvent dispatcher_stop_;  // stops the reaper loop on drain_and_stop()
};

}  // namespace xv6::router

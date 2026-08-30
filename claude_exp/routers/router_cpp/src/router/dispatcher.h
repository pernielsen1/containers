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
#include "router/trace_recorder.h"
#include "shared/log_throttle.h"
#include "shared/stats.h"
#include "shared/stop_event.h"

namespace router {

struct PendingEntry {
    int up_fd = -1;
    std::shared_ptr<std::mutex> up_write_lock;
    std::string upstream_stan;
    std::chrono::steady_clock::time_point created_at;
    // Distinct from created_at (set once this entry is added to pending_, i.e. after crypto +
    // right before the downstream send - used for the TTL reaper and downstream_rtt).
    // started_at is the true transaction start (RoutedMessage::enqueued_at, before queue wait
    // and the upstream-leg crypto call) - used for the end-to-end "total" latency bucket.
    std::chrono::steady_clock::time_point started_at;
};

struct RoutedMessage {
    std::map<std::string, std::string> req;
    int up_fd = -1;
    std::shared_ptr<std::mutex> up_write_lock;
    sockaddr_storage addr{};
    std::vector<uint8_t> raw;  // wire bytes as received - feeds TraceRecorder::start()
    std::chrono::steady_clock::time_point enqueued_at{};  // stamped by Dispatcher::submit()
};

// One row of Dispatcher::pending_snapshot()'s output. A plain struct rather than nlohmann::json
// directly, so dispatcher.h doesn't need to pull in json.hpp - callers (router_main.cpp) convert
// to JSON at the point they already depend on it.
struct PendingSnapshotEntry {
    std::string router_stan;
    std::string upstream_stan;
    double age_seconds = 0.0;
};

// Worker pool + STAN rewrite + pending map. Direct 1:1 port of the Java concurrency model --
// single mutex-guarded map, linear-scan reaper, no sharding. Routes 0100 upstream -> crypto ->
// downstream. Routes 0110/0130/0430 downstream -> upstream (via STAN lookup).
class Dispatcher {
public:
    Dispatcher(const RouterConfig& cfg, DownstreamConnection& downstream, CryptoClient& crypto,
               shared::Stats& stats, shared::StopEvent& reconnect_event);
    ~Dispatcher();
    Dispatcher(const Dispatcher&) = delete;
    Dispatcher& operator=(const Dispatcher&) = delete;

    // Spawns cfg.worker_threads worker threads running worker_loop(), cfg.response_worker_threads
    // response worker threads running response_worker_loop(), plus one pending-reaper thread.
    void start();

    void submit(RoutedMessage msg);                                          // blocking enqueue (backpressure)
    // Enqueues a downstream response (0110/0130/0430) for handling by the response worker pool,
    // instead of processing it inline on the caller's (ds-receiver) thread. Keeps the 0110 leg's
    // crypto call from being a single-threaded bottleneck that competes with the 0100 leg's queue.
    // raw is the wire bytes as received - feeds TraceRecorder's downstream_recv hop.
    void submit_response(std::map<std::string, std::string> resp, std::vector<uint8_t> raw = {});
    void handle_response(const std::map<std::string, std::string>& resp, const std::vector<uint8_t>& raw = {});
    std::map<std::string, int> purge();                                        // operator drain; returns dropped counts
    void drain_and_stop();                                                     // poison-pill sentinels + join

    // Read-only view of in-flight transactions (downstream request sent, no response yet) for
    // live diagnosis - e.g. "why is this router stuck", without waiting for pending_ttl_seconds
    // to expire and decline them. Sorted oldest-first so a stuck transaction sorts to the top.
    std::vector<PendingSnapshotEntry> pending_snapshot();

    // Exposed for the /trace route (router_main.cpp) - mirrors router_py's public `dispatcher.trace`.
    TraceRecorder& trace() { return trace_; }

private:
    friend class DispatcherTestAccess;  // test-only access to pending_/queue_/stan_counter_

    void worker_loop();
    void response_worker_loop();
    void reaper_loop();
    void process(RoutedMessage& msg);
    std::string next_stan();

    const RouterConfig& cfg_;
    DownstreamConnection& downstream_;
    CryptoClient& crypto_;
    shared::Stats& stats_;
    shared::StopEvent& reconnect_event_;

    std::deque<std::optional<RoutedMessage>> queue_;  // nullopt = poison pill
    std::mutex queue_mutex_;
    std::condition_variable queue_cv_not_full_;
    std::condition_variable queue_cv_not_empty_;

    struct ResponseItem {
        std::map<std::string, std::string> resp;
        std::vector<uint8_t> raw;
    };
    std::deque<std::optional<ResponseItem>> response_queue_;  // nullopt = poison pill
    std::mutex response_queue_mutex_;
    std::condition_variable response_queue_cv_not_full_;
    std::condition_variable response_queue_cv_not_empty_;

    std::unordered_map<std::string, PendingEntry> pending_;
    std::mutex pending_mutex_;

    TraceRecorder trace_;
    shared::LogThrottle throttle_{200};

    std::atomic<int> stan_counter_{0};

    std::vector<std::thread> workers_;
    std::vector<std::thread> response_workers_;
    std::thread reaper_;
    shared::StopEvent dispatcher_stop_;  // stops the reaper loop on drain_and_stop()
};

}  // namespace router

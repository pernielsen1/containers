#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <thread>

#include <catch2/catch_test_macros.hpp>

#include "router/dispatcher.h"
#include "router/downstream_connection.h"
#include "shared/ebcdic.h"
#include "shared/iso_codec.h"
#include "shared/log.h"

// Port of router_py's tests/test_dispatcher_resilience.py / router_java's
// DispatcherResilienceTest.java.

using namespace xv6::router;
using namespace xv6::shared;

namespace xv6::router {

// Test-only access to Dispatcher's private members. There's no reflection in C++ the way
// router_java's tests use it - this friend class is the equivalent backdoor, scoped to exactly
// what these tests need.
class DispatcherTestAccess {
public:
    static void inject_pending(Dispatcher& d, const std::string& stan, PendingEntry entry) {
        std::lock_guard<std::mutex> lock(d.pending_mutex_);
        d.pending_[stan] = std::move(entry);
    }

    static size_t pending_size(Dispatcher& d) {
        std::lock_guard<std::mutex> lock(d.pending_mutex_);
        return d.pending_.size();
    }

    // +1 because next_stan() increments before formatting - matches dispatcher.cpp's own logic.
    static int next_stan_value(Dispatcher& d) { return d.stan_counter_.load() + 1; }

    static void drain_one_from_queue(Dispatcher& d) {
        std::lock_guard<std::mutex> lock(d.queue_mutex_);
        if (!d.queue_.empty()) {
            d.queue_.pop_front();
            d.queue_cv_not_full_.notify_one();
        }
    }
};

// Test-only: build a DownstreamConnection from an already-connected fd pair instead of a real
// IMS Connect handshake - Dispatcher only ever calls send(frame) on it in these tests, which is
// a plain send_exact() under the hood, so a socket pair stands in fine.
class DownstreamConnectionTestFactory {
public:
    static DownstreamConnection make(int to_fd, int from_fd) {
        DownstreamConnection conn;
        conn.to_fd_ = to_fd;
        conn.from_fd_ = from_fd;
        return conn;
    }
};

}  // namespace xv6::router

namespace {

struct SocketPair {
    int a, b;
    SocketPair() {
        int fds[2];
        REQUIRE(::socketpair(AF_UNIX, SOCK_STREAM, 0, fds) == 0);
        a = fds[0];
        b = fds[1];
        timeval tv{5, 0};
        ::setsockopt(b, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    }
    ~SocketPair() {
        ::close(a);
        ::close(b);
    }
};

RouterConfig make_cfg(int queue_maxsize, int pending_ttl_seconds, int worker_threads) {
    RouterConfig cfg;
    cfg.name = "test_router";
    cfg.command_port = 19100;
    cfg.upstream.mode = "server";
    cfg.upstream.port = 15000;
    cfg.downstream.host = "localhost";
    cfg.downstream.port = 15001;
    cfg.downstream.irm_id = xv6::shared::to_ebcdic("IRM0001", 8);
    cfg.downstream.client_id = xv6::shared::to_ebcdic("CLIENT01", 8);
    // Nothing listening on port 1 - CryptoClient::validate() fails fast (connection refused) and
    // returns "" without needing a mock/fake, matching every real failure path it already has.
    cfg.crypto.host = "localhost";
    cfg.crypto.port = 1;
    cfg.crypto.plugin_id = "test-plugin";
    cfg.crypto.bearer_token = "test-token";
    cfg.worker_threads = worker_threads;
    cfg.response_worker_threads = worker_threads;
    cfg.queue_maxsize = queue_maxsize;
    cfg.pending_ttl_seconds = pending_ttl_seconds;
    return cfg;
}

// Bundles everything a Dispatcher needs: a real CryptoClient pointed at an unreachable port, a
// real DownstreamConnection built from a socket pair (declared before `downstream` below so it
// constructs first - C++ initializes members in declaration order, not initializer-list order),
// and the Dispatcher itself.
struct TestHarness {
    RouterConfig cfg;
    xv6::shared::Stats stats{std::nullopt};
    xv6::shared::StopEvent reconnect_event;
    CryptoClient crypto;
    SocketPair ds_to_pair;    // downstream "to" leg - test never reads ds_to_pair.b, just lets
                               // bytes accumulate; none of these tests exercise the response path
    SocketPair ds_from_pair;  // downstream "from" leg - never used, DownstreamConnection just
                               // needs a valid fd to own/close
    DownstreamConnection downstream;
    Dispatcher dispatcher;

    explicit TestHarness(int queue_maxsize, int pending_ttl_seconds, int worker_threads)
        : cfg(make_cfg(queue_maxsize, pending_ttl_seconds, worker_threads)),
          crypto(cfg.crypto, 5, 30),
          downstream(DownstreamConnectionTestFactory::make(ds_to_pair.a, ds_from_pair.a)),
          dispatcher(cfg, downstream, crypto, stats, reconnect_event) {}
};

RoutedMessage make_msg(std::map<std::string, std::string> req, int up_fd,
                        std::shared_ptr<std::mutex> write_lock) {
    RoutedMessage msg;
    msg.req = std::move(req);
    msg.up_fd = up_fd;
    msg.up_write_lock = std::move(write_lock);
    return msg;
}

bool any_log_contains(const std::string& needle) {
    auto lines = xv6::shared::Logger::instance().buffered_lines();
    return std::any_of(lines.begin(), lines.end(),
                        [&](const std::string& l) { return l.find(needle) != std::string::npos; });
}

}  // namespace

TEST_CASE("pending entry TTL expiry sends local decline", "[dispatcher]") {
    TestHarness h(3, 1, 1);
    h.dispatcher.start();

    SocketPair up_pair;
    auto write_lock = std::make_shared<std::mutex>();

    std::map<std::string, std::string> req = {
        {"t", "0100"}, {"2", "4111111111111111"}, {"3", "000000"}, {"4", "000000000100"}, {"11", "000001"}};
    h.dispatcher.submit(make_msg(req, up_pair.a, write_lock));

    // No response ever arrives, so after pending_ttl_seconds (1s) the reaper sends a local
    // decline back upstream - read it off the paired socket (up_pair.b's SO_RCVTIMEO turns a
    // stuck read into a clear test failure instead of a hang).
    FramingConfig upstream_framing;  // defaults already match router_1's ASCII/4-byte framing
    auto decline_frame = xv6::shared::read_message(up_pair.b, upstream_framing);
    auto resp = xv6::shared::iso_codec::decode(decline_frame);
    REQUIRE(resp["11"] == "000001");
    REQUIRE(resp["39"] == "91");

    h.dispatcher.drain_and_stop();
}

TEST_CASE("submit blocks when queue is full", "[dispatcher]") {
    TestHarness h(1, 100, 1);
    // Deliberately not calling start() - nothing drains the queue, so it fills up.

    SocketPair up_pair;
    auto write_lock = std::make_shared<std::mutex>();

    std::map<std::string, std::string> req1 = {{"t", "0100"}, {"2", "4111111111111111"}, {"11", "000001"}};
    h.dispatcher.submit(make_msg(req1, up_pair.a, write_lock));

    std::atomic<bool> second_submitted{false};
    std::thread t([&] {
        std::map<std::string, std::string> req2 = {{"t", "0100"}, {"2", "4111111111111111"}, {"11", "000002"}};
        h.dispatcher.submit(make_msg(req2, up_pair.a, write_lock));
        second_submitted = true;
    });

    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    REQUIRE_FALSE(second_submitted.load());

    DispatcherTestAccess::drain_one_from_queue(h.dispatcher);
    t.join();
    REQUIRE(second_submitted.load());
}

TEST_CASE("STAN collision is logged", "[dispatcher]") {
    TestHarness h(10, 100, 1);
    h.dispatcher.start();

    SocketPair up_pair;
    auto write_lock = std::make_shared<std::mutex>();

    int next_stan_value = DispatcherTestAccess::next_stan_value(h.dispatcher);
    char buf[8];
    std::snprintf(buf, sizeof(buf), "%06d", next_stan_value % 1'000'000);
    std::string next_stan(buf);

    PendingEntry entry;
    entry.up_fd = up_pair.a;
    entry.up_write_lock = write_lock;
    entry.upstream_stan = "000000";
    entry.created_at = std::chrono::steady_clock::now();
    DispatcherTestAccess::inject_pending(h.dispatcher, next_stan, entry);

    std::map<std::string, std::string> req = {{"t", "0100"}, {"2", "4111111111111111"}, {"11", "000001"}};
    h.dispatcher.submit(make_msg(req, up_pair.a, write_lock));
    std::this_thread::sleep_for(std::chrono::milliseconds(300));

    REQUIRE(any_log_contains("still-outstanding"));

    h.dispatcher.drain_and_stop();
}

TEST_CASE("drain_and_stop logs and clears abandoned pending", "[dispatcher]") {
    TestHarness h(5, 100, 1);
    h.dispatcher.start();

    SocketPair up_pair;
    auto write_lock = std::make_shared<std::mutex>();

    PendingEntry entry;
    entry.up_fd = up_pair.a;
    entry.up_write_lock = write_lock;
    entry.upstream_stan = "100042";
    entry.created_at = std::chrono::steady_clock::now();
    DispatcherTestAccess::inject_pending(h.dispatcher, "000042", entry);

    h.dispatcher.drain_and_stop();

    REQUIRE(DispatcherTestAccess::pending_size(h.dispatcher) == 0);
    REQUIRE(any_log_contains("router_stan=000042 still pending"));
    REQUIRE(any_log_contains("upstream_stan=100042"));
    REQUIRE(any_log_contains("abandoned 1 pending transaction"));
}

TEST_CASE("purge drops queued and pending counts", "[dispatcher]") {
    TestHarness h(5, 100, 1);
    // No start() - queue stays populated with nothing draining it.

    SocketPair up_pair;
    auto write_lock = std::make_shared<std::mutex>();

    for (int i = 0; i < 3; ++i) {
        char stan[8];
        std::snprintf(stan, sizeof(stan), "%06d", i);
        std::map<std::string, std::string> req = {{"t", "0100"}, {"2", "4111111111111111"}, {"11", stan}};
        h.dispatcher.submit(make_msg(req, up_pair.a, write_lock));
    }

    PendingEntry entry;
    entry.up_fd = up_pair.a;
    entry.up_write_lock = write_lock;
    entry.upstream_stan = "000000";
    entry.created_at = std::chrono::steady_clock::now();
    DispatcherTestAccess::inject_pending(h.dispatcher, "999999", entry);

    auto result = h.dispatcher.purge();
    REQUIRE(result["queue_dropped"] == 3);
    REQUIRE(result["pending_dropped"] == 1);
}

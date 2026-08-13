#pragma once

#include <map>
#include <memory>
#include <optional>
#include <string>
#include <thread>

#include "router/crypto_client.h"
#include "router/dispatcher.h"
#include "router/downstream_connection.h"
#include "router/router_config.h"
#include "router/upstream.h"
#include "shared/stats.h"
#include "shared/stop_event.h"

namespace router {

class RouterSession {
public:
    // Returns a heap-owned session rather than a by-value RouterSession: Dispatcher captures a
    // raw reference to this object's downstream_ member at construction time, so relocating the
    // RouterSession afterward (a move constructor, or the extra move std::optional::emplace()
    // performs internally even when handed an already-built rvalue) would leave that reference
    // dangling. Constructing once on the heap and never moving it sidesteps the problem entirely.
    static std::unique_ptr<RouterSession> connect(const RouterConfig& cfg, shared::Stats& stats,
                                                   shared::StopEvent& stop_event);

    RouterSession(RouterSession&& other) = delete;
    RouterSession(const RouterSession&) = delete;
    RouterSession& operator=(const RouterSession&) = delete;
    RouterSession& operator=(RouterSession&& other) = delete;

    void run_until_disconnect(UpstreamServer* srv_sock);

    Dispatcher* dispatcher();

private:
    RouterSession(const RouterConfig& cfg, DownstreamConnection&& downstream,
                  std::unique_ptr<CryptoClient> crypto, shared::Stats& stats,
                  shared::StopEvent& stop_event, std::unique_ptr<shared::StopEvent>&& reconnect_event);

    void handle_upstream(int fd, const sockaddr_storage& addr,
                        const std::shared_ptr<std::mutex>& write_lock);
    void forward_0800(const std::map<std::string, std::string>& req);
    void forward_0810(const std::map<std::string, std::string>& resp);
    void downstream_receiver();
    void teardown(std::thread& up_thread);

    const RouterConfig& cfg_;
    DownstreamConnection downstream_;
    std::unique_ptr<CryptoClient> crypto_;
    std::unique_ptr<Dispatcher> dispatcher_;
    shared::Stats& stats_;
    shared::StopEvent& stop_event_;
    std::unique_ptr<shared::StopEvent> reconnect_event_;

    int upstream_fd_ = -1;
    std::shared_ptr<std::mutex> upstream_write_lock_;
    std::unique_ptr<std::mutex> upstream_ref_mutex_ = std::make_unique<std::mutex>();

    std::thread ds_receiver_thread_;
};

}  // namespace router

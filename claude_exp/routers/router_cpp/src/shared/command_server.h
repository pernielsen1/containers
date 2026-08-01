#pragma once

#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <thread>
#include <vector>

#include <httplib.h>

#include "shared/stats.h"
#include "shared/stop_event.h"

namespace xv6::shared {

class CommandServer {
public:
    CommandServer(int port, Stats& stats, StopEvent& stop_event,
                  const std::string& bind_host = "127.0.0.1",
                  std::optional<std::string> auth_token = {});
    ~CommandServer();
    CommandServer(const CommandServer&) = delete;
    CommandServer& operator=(const CommandServer&) = delete;

    using Handler = std::function<void(const httplib::Request&, httplib::Response&)>;
    void register_route(const std::string& path, const std::vector<std::string>& methods,
                       bool protected_route, Handler handler);

    void start();
    void stop();

private:
    void setup_builtin_routes();
    Handler wrap_handler(bool protected_route, Handler handler);

    int port_;
    Stats& stats_;
    StopEvent& stop_event_;
    std::string bind_host_;
    std::optional<std::string> auth_token_;

    std::unique_ptr<httplib::Server> server_;
    std::unique_ptr<std::thread> listen_thread_;
};

}  // namespace xv6::shared

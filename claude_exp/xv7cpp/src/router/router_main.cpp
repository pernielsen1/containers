#include <cstdlib>
#include <iostream>
#include <memory>
#include <random>
#include <thread>

#include <nlohmann/json.hpp>

#include "router/router_config.h"
#include "router/router_session.h"
#include "router/upstream.h"
#include "shared/command_server.h"
#include "shared/log.h"
#include "shared/stats.h"
#include "shared/stop_event.h"

using json = nlohmann::json;
using namespace xv6::router;
using namespace xv6::shared;

namespace {

std::string parse_config_arg(int argc, char** argv) {
    for (int i = 1; i < argc - 1; i++) {
        if (std::string(argv[i]) == "--config") {
            return argv[i + 1];
        }
    }
    throw std::runtime_error("missing --config <path>");
}

void send_json(httplib::Response& res, int status, const json& obj) {
    res.set_header("Content-Type", "application/json");
    res.set_content(obj.dump(), "application/json");
    res.status = status;
}

void wait_reestablish(StopEvent& stop_event, const RouterConfig& cfg) {
    static std::mt19937 gen(std::random_device{}());
    std::uniform_real_distribution<> dis(0.0, cfg.reconnect_jitter_seconds);

    int total_wait_ms = cfg.reestablish_seconds * 1000 + (int)(dis(gen) * 1000);
    int poll_interval_ms = 100;

    for (int elapsed = 0; elapsed < total_wait_ms; elapsed += poll_interval_ms) {
        if (stop_event.is_set()) break;
        stop_event.wait_for(std::chrono::milliseconds(poll_interval_ms));
    }
}

}  // namespace

int main(int argc, char** argv) {
    try {
        auto cfg_path = parse_config_arg(argc, argv);
        RouterConfig cfg = RouterConfig::from_file(cfg_path);
        StopEvent stop_event;
        Stats stats(cfg.yellow_threshold_seconds);

        Logger::instance().set_level(*parse_log_level(cfg.log_level));
        CommandServer cmd(cfg.command_port, stats, stop_event, cfg.command_bind_host,
                          cfg.command_auth_token);

        std::shared_ptr<Dispatcher> active_dispatcher;
        std::mutex active_dispatcher_mutex;
        cmd.register_route("/dispatcher/purge", {"POST"}, /*protected=*/true,
                          [&](const httplib::Request&, httplib::Response& res) {
                              std::lock_guard lock(active_dispatcher_mutex);
                              if (!active_dispatcher) {
                                  send_json(res, 503, {{"error", "no active session"}});
                                  return;
                              }
                              send_json(res, 200, active_dispatcher->purge());
                          });
        cmd.start();

        std::unique_ptr<UpstreamServer> srv_sock;
        if (cfg.upstream.mode == "server") {
            srv_sock = std::make_unique<UpstreamServer>(cfg.upstream);
        }

        while (!stop_event.is_set()) {
            std::unique_ptr<RouterSession> session;
            try {
                session = RouterSession::connect(cfg, stats, stop_event);
            } catch (const std::exception& e) {
                LOG_WARNING(std::string("failed to connect downstream: ") + e.what());
                wait_reestablish(stop_event, cfg);
                continue;
            }

            {
                std::lock_guard lock(active_dispatcher_mutex);
                active_dispatcher = std::shared_ptr<Dispatcher>(session->dispatcher(), [](Dispatcher*) {});
            }
            session->run_until_disconnect(srv_sock.get());
            {
                std::lock_guard lock(active_dispatcher_mutex);
                active_dispatcher = nullptr;
            }

            if (!stop_event.is_set()) {
                wait_reestablish(stop_event, cfg);
            }
        }

        cmd.stop();
        return 0;
    } catch (const std::exception& e) {
        LOG_ERROR(std::string("fatal: ") + e.what());
        return 1;
    }
}

#include <chrono>
#include <cstdlib>
#include <exception>
#include <memory>
#include <thread>

#include <nlohmann/json.hpp>

#include "router/router_config.h"
#include "shared/base64.h"
#include "shared/command_server.h"
#include "shared/iso_codec.h"
#include "shared/log.h"
#include "shared/pans_defined.h"
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

// Stub: no OpenSSL, no PIN/ARQC/CVV2/AAV math - just reports whether the PAN is provisioned.
// Real cryptographic validation lives in routers/crypto_host/ (the shared container); this stub
// exists so router_cpp can still be built/tested standalone without it.
json validate(const std::string& pan, const json& f47_in,
              const std::map<std::string, PanRecord>& pans) {
    json f47 = f47_in;
    f47["response_code"] = pans.find(pan) == pans.end() ? "14" : "00";
    return f47;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        auto cfg_path = parse_config_arg(argc, argv);
        auto cfg = RouterConfig::from_file(cfg_path);
        auto pans = load_pans_defined(cfg.pans_defined_path);

        StopEvent stop_event;
        Stats stats(cfg.yellow_threshold_seconds);

        Logger::instance().set_level(*parse_log_level(cfg.log_level));
        CommandServer cmd(cfg.crypto.command_port, stats, stop_event, "0.0.0.0", {});
        cmd.start();

        // Separate httplib::Server for the plugin-execution route, bound to its own port --
        // mirrors the Java version's two independent HttpServer instances. SSLServer derives
        // from Server (same .Post/.listen/.stop surface), so ssl_active only decides which
        // concrete type gets constructed.
        std::unique_ptr<httplib::Server> plugin_server_ptr;
        if (cfg.crypto.ssl_active) {
            plugin_server_ptr = std::make_unique<httplib::SSLServer>(
                cfg.crypto.certfile.c_str(), cfg.crypto.keyfile.c_str(),
                cfg.crypto.cafile.empty() ? nullptr : cfg.crypto.cafile.c_str());
        } else {
            plugin_server_ptr = std::make_unique<httplib::Server>();
        }
        httplib::Server& plugin_server = *plugin_server_ptr;
        plugin_server.Post(
            "/sys/v1/plugins/([^/]+)",
            [&](const httplib::Request& req, httplib::Response& res) {
                std::string plugin_id = req.matches[1];
                if (plugin_id != cfg.crypto.plugin_id) {
                    res.status = 404;
                    return;
                }
                if (req.get_header_value("Authorization") != "Bearer " + cfg.crypto.bearer_token) {
                    send_json(res, 401, {{"error", "unauthorized"}});
                    return;
                }

                // router_stan isn't part of the Fortanix plugin contract - it's an extra field
                // the router sends purely so this actor's logs can be joined with the router's
                // logs on the same transaction (empty when a caller doesn't send one, e.g. tests
                // hitting this route directly).
                std::string router_stan;
                try {
                    auto body = json::parse(req.body);
                    std::string pan = body.at("f2").get<std::string>();
                    std::string f47_str = body.value("f47", std::string(""));
                    router_stan = body.value("router_stan", std::string(""));
                    json f47 = iso_codec::f47_decode(f47_str);
                    stats.record_recv();

                    json enriched = validate(pan, f47, pans);
                    LOG_DEBUG("validated pan=" + pan + " router_stan=" + router_stan);

                    json envelope = {{"f47", enriched.dump()}};
                    std::string envelope_str = envelope.dump();
                    std::string b64 = base64_encode(
                        std::vector<uint8_t>(envelope_str.begin(), envelope_str.end()));

                    res.set_header("Content-Type", "application/json");
                    res.set_content(json(b64).dump(), "application/json");
                    res.status = 200;
                    stats.record_sent();
                } catch (const std::exception& e) {
                    LOG_WARNING("validate failed router_stan=" + router_stan + ": " + e.what());
                    send_json(res, 400, {{"error", e.what()}});
                }
            });

        std::thread plugin_thread([&] { plugin_server.listen("0.0.0.0", cfg.crypto.port); });
        LOG_INFO("crypto_host listening on port " + std::to_string(cfg.crypto.port));

        while (!stop_event.is_set()) {
            stop_event.wait_for(std::chrono::seconds(1));
        }

        plugin_server.stop();
        if (plugin_thread.joinable()) plugin_thread.join();
        cmd.stop();
        return 0;
    } catch (const std::exception& e) {
        LOG_ERROR(std::string("fatal: ") + e.what());
        return 1;
    }
}

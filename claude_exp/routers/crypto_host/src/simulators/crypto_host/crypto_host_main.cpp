#include <chrono>
#include <cstdlib>
#include <exception>
#include <thread>

#include <nlohmann/json.hpp>

#include "router/router_config.h"
#include "shared/base64.h"
#include "shared/command_server.h"
#include "shared/crypto_utils.h"
#include "shared/iso_codec.h"
#include "shared/log.h"
#include "shared/pans_defined.h"
#include "shared/stats.h"
#include "shared/stop_event.h"

using json = nlohmann::json;
using namespace xv6::router;
using namespace xv6::shared;
using namespace xv6::shared::crypto_utils;

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


// Pure business logic: given a PAN and the request's decoded field-47 JSON, run the
// validate_0100/validate_0110 checks and return the enriched field-47 object.
json validate(const std::string& pan, const json& f47_in,
              const std::map<std::string, PanRecord>& pans) {
    json f47 = f47_in;

    auto it = pans.find(pan);
    if (it == pans.end()) {
        f47["response_code"] = "14";
        return f47;
    }
    const PanRecord& rec = it->second;
    std::string message_type = f47.value("message_type", std::string(""));
    std::string rc = "00";

    if (f47.contains("f52")) {
        if (!verify_pin(pan, f47.at("f52").get<std::string>(), rec.pek, rec.pin)) {
            rc = "55";
        }
    }
    if (f47.contains("f55") && message_type == "0100" && rc == "00") {
        if (!verify_arqc(pan, rec.pan_seq, rec.imk_ac, f47.at("f55"))) {
            rc = "82";
        }
    }
    if (f47.contains("f55") && message_type == "0110") {
        std::string udk_hex = derive_udk(rec.imk_ac, pan, rec.pan_seq);
        std::string atc_hex = f47.at("f55").value("atc", std::string(""));
        std::string sk_hex = derive_session_key(udk_hex, atc_hex);
        std::string cryptogram = f47.at("f55").value("cryptogram", std::string(""));
        auto arpc = calculate_arpc_method1(cryptogram, rc, sk_hex);
        f47["f55"]["arpc"] = base64_encode(arpc);
    }
    if (f47.contains("cvv2") && rc == "00") {
        std::string expiry = f47.value("f14", std::string(""));
        if (!verify_cvv2(pan, expiry, f47.at("cvv2").get<std::string>(), rec.cvk)) {
            rc = "N7";
        }
    }
    if (f47.contains("aav") && rc == "00") {
        if (!verify_aav(f47, rec.aav_key, pan)) {
            rc = "82";
        }
    }

    f47["response_code"] = rc;
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
        // mirrors the Java version's two independent HttpServer instances.
        //
        // NOTE (2026-07-31): the client-side bottleneck (router_py's 0110 leg running inline on a
        // single thread, capping it at ~1/latency throughput) was fixed on the router_py side instead
        // (see performance_result_20260730.md) - default thread pool here. Bumping this server's
        // thread pool to 32 was tried and made every tps level *worse* (including regressing an
        // already-passing 100 tps run to p50=5070ms) - this host is CPU-constrained, and more
        // server threads than cores oversubscribes it rather than adding real capacity. Left at
        // the cpp-httplib default (max(8, hardware_concurrency()-1)).
        httplib::Server plugin_server;
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

                try {
                    auto body = json::parse(req.body);
                    std::string pan = body.at("f2").get<std::string>();
                    std::string f47_str = body.value("f47", std::string(""));
                    json f47 = iso_codec::f47_decode(f47_str);
                    stats.record_recv();

                    json enriched = validate(pan, f47, pans);

                    json envelope = {{"f47", enriched.dump()}};
                    std::string envelope_str = envelope.dump();
                    std::string b64 = base64_encode(
                        std::vector<uint8_t>(envelope_str.begin(), envelope_str.end()));

                    res.set_header("Content-Type", "application/json");
                    res.set_content(json(b64).dump(), "application/json");
                    res.status = 200;
                    stats.record_sent();
                } catch (const std::exception& e) {
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

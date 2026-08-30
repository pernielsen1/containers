#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <exception>
#include <map>
#include <memory>
#include <thread>
#include <vector>

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

bool is_no_response_chaos(
    const std::string& pan, const std::string& operation,
    const std::map<std::string, std::vector<std::string>>& no_response_pans) {
    auto it = no_response_pans.find(pan);
    if (it == no_response_pans.end()) return false;
    const auto& ops = it->second;
    return std::find(ops.begin(), ops.end(), operation) != ops.end();
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
        // mirrors the Java version's two independent HttpServer instances. SSLServer derives
        // from Server (same .Post/.listen/.stop surface), so ssl_active only decides which
        // concrete type gets constructed - same pattern as each language's own bundled
        // crypto_host stub (see router_cpp/src/simulators/crypto_host/crypto_host_main.cpp).
        //
        // NOTE (2026-07-31): the client-side bottleneck (router_py's 0110 leg running inline on a
        // single thread, capping it at ~1/latency throughput) was fixed on the router_py side instead
        // (see performance.md) - default thread pool here. Bumping this server's
        // thread pool to 32 was tried and made every tps level *worse* (including regressing an
        // already-passing 100 tps run to p50=5070ms) - this host is CPU-constrained, and more
        // server threads than cores oversubscribes it rather than adding real capacity. Left at
        // the cpp-httplib default (max(8, hardware_concurrency()-1)) at the time.
        //
        // NOTE (2026-08-16): that earlier measurement predates set_keep_alive_max_count(10000)
        // below (was still the cpp-httplib default of 5), so every one of those 32 threads was
        // regularly doing real CPU-bound RSA handshake work - genuine oversubscription on this
        // 8-core host. cpp-httplib is thread-per-connection: a thread stays pinned to its
        // connection for the connection's whole lifetime, including idle time between keep-alive
        // requests, not just while actively handling a request. With keep-alive connections now
        // long-lived, router_java's Dispatcher alone holds up to workerThreads +
        // responseWorkerThreads = 16 of them open simultaneously - one router_stan's crypto call
        // routed to the 9th+ concurrently-open connection then has to wait for one of the
        // hardware_concurrency()-1 = 7 (i.e. 8, the max(8,...) floor) pool threads to free up,
        // which under all-10000-keep-alive it never does, surfacing as connect timeouts / TLS
        // "internal_error" (reproduced directly: 16 same-JVM threads holding open connections,
        // exactly 8 succeed and 8 hang until timeout, matching this host's core count exactly).
        // Sized to comfortably clear that 16-connection worst case with headroom rather than
        // matched 1:1 - these extra threads sit blocked on an idle keep-alive read almost all the
        // time now (one-time-per-connection handshake cost, not per-request), so this does not
        // reintroduce the CPU oversubscription the 07-31 measurement found; it isn't 32 CPU-bound
        // threads, it's a handful of active threads plus many idle ones.
        std::unique_ptr<httplib::Server> plugin_server_ptr;
        if (cfg.crypto.ssl_active) {
            plugin_server_ptr = std::make_unique<httplib::SSLServer>(
                cfg.crypto.certfile.c_str(), cfg.crypto.keyfile.c_str(),
                cfg.crypto.cafile.empty() ? nullptr : cfg.crypto.cafile.c_str());
        } else {
            plugin_server_ptr = std::make_unique<httplib::Server>();
        }
        httplib::Server& plugin_server = *plugin_server_ptr;
        // cpp-httplib defaults keep_alive_max_count to 5: with SSL active, every persistent
        // connection recycling past that count forces a fresh (RSA) TLS handshake. Under stress-test
        // concurrency that repeated handshake cost - not the thread count above, already found to be
        // CPU-bound - is what saturates this host and surfaces as "fatal alert: internal_error" on
        // the client side. Raised well past any single run's request count per connection so
        // handshakes happen once per connection, not once per 5 requests.
        plugin_server.set_keep_alive_max_count(10000);
        plugin_server.set_tcp_nodelay(true);
        // Must accompany the keep_alive bump above, not stand alone - see this block's own NOTE
        // (2026-08-16) above the plugin_server_ptr construction for why. 24 clears router_java's
        // 16-connection worst case (workerThreads + responseWorkerThreads) with headroom for the
        // command-server thread and any other concurrent client, without matching it 1:1.
        plugin_server.new_task_queue = [] { return new httplib::ThreadPool(24); };
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
                    std::string operation = body.value("operation", std::string(""));
                    std::string f47_str = body.value("f47", std::string(""));
                    router_stan = body.value("router_stan", std::string(""));
                    json f47 = iso_codec::f47_decode(f47_str);
                    stats.record_recv();

                    if (is_no_response_chaos(pan, operation, cfg.crypto.no_response_pans)) {
                        // Bounded, not forever - the caller's own timeout (CryptoClient's
                        // request-leg default / short response-leg default) always decides the
                        // caller-visible outcome well before this fires; the bound only reclaims
                        // this server thread instead of leaking it - see router_py's
                        // simulators/crypto_host/main.py::no_response_pans, same rationale and
                        // same 2s bound.
                        LOG_WARNING("chaos: simulating no response for pan=" + pan +
                                    " operation=" + operation + " router_stan=" + router_stan);
                        std::this_thread::sleep_for(std::chrono::seconds(2));
                        send_json(res, 504, {{"error", "chaos: no response"}});
                        return;
                    }

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

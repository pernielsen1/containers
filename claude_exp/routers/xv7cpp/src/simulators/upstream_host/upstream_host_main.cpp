#include <sys/socket.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <filesystem>
#include <fstream>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <thread>
#include <vector>

#include <nlohmann/json.hpp>

#include "router/router_config.h"
#include "router/upstream.h"
#include "shared/command_server.h"
#include "shared/framing.h"
#include "shared/iso_codec.h"
#include "shared/log.h"
#include "shared/stats.h"
#include "shared/stop_event.h"

using json = nlohmann::json;
using namespace xv6::router;
using namespace xv6::shared;

namespace {

const std::string kInputDir = "upstream_1_input";
const std::string kCsvFilename = "test_cases.csv";

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

std::vector<std::string> split_semicolon(const std::string& line) {
    std::vector<std::string> out;
    std::string cur;
    for (char c : line) {
        if (c == ';') {
            out.push_back(cur);
            cur.clear();
        } else {
            cur.push_back(c);
        }
    }
    out.push_back(cur);
    return out;
}

// Semicolon-delimited, UTF-8 with a possible leading BOM. Column headers are ISO 8583 field
// numbers; columns that aren't known fields (e.g. a test-only "expected_39" column) are dropped.
std::vector<std::map<std::string, std::string>> parse_csv(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("failed to open csv: " + path);
    std::string content((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());

    if (content.size() >= 3 && static_cast<unsigned char>(content[0]) == 0xEF &&
        static_cast<unsigned char>(content[1]) == 0xBB &&
        static_cast<unsigned char>(content[2]) == 0xBF) {
        content.erase(0, 3);
    }

    std::vector<std::string> lines;
    std::istringstream ss(content);
    std::string line;
    while (std::getline(ss, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (!line.empty()) lines.push_back(line);
    }

    std::vector<std::map<std::string, std::string>> rows;
    if (lines.empty()) return rows;

    auto headers = split_semicolon(lines[0]);
    for (size_t i = 1; i < lines.size(); i++) {
        auto values = split_semicolon(lines[i]);
        std::map<std::string, std::string> row;
        for (size_t c = 0; c < headers.size() && c < values.size(); c++) {
            if (iso_codec::is_known_field(headers[c])) {
                row[headers[c]] = values[c];
            }
        }
        rows.push_back(std::move(row));
    }
    return rows;
}

std::string next_stan(std::atomic<int>& counter) {
    int next = (counter.fetch_add(1) + 1) % 1'000'000;
    char buf[8];
    std::snprintf(buf, sizeof(buf), "%06d", next);
    return std::string(buf);
}

// Shared connection/session state, referenced by the connect loop, send loop, and command routes.
// All fields outlive every thread that touches them -- every background thread started from
// main() is joined before main() returns.
struct SessionState {
    std::mutex conn_mutex;
    int fd = -1;
    std::shared_ptr<std::mutex> write_lock;
    std::atomic<bool> connected{false};
    std::atomic<bool> disconnect_flag{false};

    std::mutex pending_mutex;
    std::map<std::string, std::map<std::string, std::string>> pending;

    std::mutex results_mutex;
    std::vector<json> results;

    std::atomic<int> stan_counter{0};

    std::mutex send_mutex;
    std::thread send_thread;
    std::atomic<bool> sending{false};

    // Stress-run state: send timestamps keyed by STAN, and a bounded latency-sample list. Capped
    // at 200k - plenty for any run duration/rate used here, keeps memory bounded on a long
    // high-rate stress run instead of growing unboundedly. Port of xv5's equivalent fields.
    static constexpr size_t kMaxLatencySamples = 200'000;
    std::mutex send_times_mutex;
    std::map<std::string, std::chrono::steady_clock::time_point> send_times;
    std::mutex latencies_mutex;
    std::vector<double> latencies_ms;
    std::atomic<long long> run_start_ms{0};
    std::atomic<long long> run_end_ms{0};
    std::atomic<int> run_sent{0};
};

long long now_ms() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
               std::chrono::system_clock::now().time_since_epoch())
        .count();
}

void receive_loop(SessionState& state, int fd, const xv6::shared::FramingConfig& framing,
                  Stats& stats) {
    while (true) {
        std::map<std::string, std::string> resp;
        try {
            auto frame = read_message(fd, framing);
            resp = iso_codec::decode(frame);
            stats.record_recv();
        } catch (const std::exception& e) {
            LOG_WARNING(std::string("upstream_host: receive loop error: ") + e.what());
            state.disconnect_flag = true;
            return;
        }

        std::string mti = resp.count("t") ? resp.at("t") : std::string("");
        if (mti == "0810") continue;
        if (mti != "0110" && mti != "0130" && mti != "0430") {
            LOG_WARNING("upstream_host: unexpected mti=" + mti);
            continue;
        }

        std::string stan = resp.count("11") ? resp.at("11") : std::string("");
        std::map<std::string, std::string> row;
        bool found = false;
        {
            std::lock_guard<std::mutex> lock(state.pending_mutex);
            auto it = state.pending.find(stan);
            if (it != state.pending.end()) {
                row = it->second;
                state.pending.erase(it);
                found = true;
            }
        }
        if (!found) {
            LOG_WARNING("upstream_host: no pending row for stan=" + stan);
            continue;
        }

        {
            std::chrono::steady_clock::time_point send_time;
            bool have_send_time = false;
            {
                std::lock_guard<std::mutex> lock(state.send_times_mutex);
                auto sit = state.send_times.find(stan);
                if (sit != state.send_times.end()) {
                    send_time = sit->second;
                    have_send_time = true;
                    state.send_times.erase(sit);
                }
            }
            if (have_send_time) {
                double latency_ms = std::chrono::duration<double, std::milli>(
                                        std::chrono::steady_clock::now() - send_time)
                                        .count();
                std::lock_guard<std::mutex> lock(state.latencies_mutex);
                if (state.latencies_ms.size() < SessionState::kMaxLatencySamples) {
                    state.latencies_ms.push_back(latency_ms);
                }
            }
        }

        for (const auto& [key, value] : resp) {
            row["resp_" + key] = value;
        }

        {
            std::lock_guard<std::mutex> lock(state.results_mutex);
            state.results.push_back(json(row));
        }
    }
}

void keepalive_loop(SessionState& state, int fd, const xv6::shared::FramingConfig& framing,
                    int ping_seconds, StopEvent& stop_event, Stats& stats) {
    while (!stop_event.is_set() && !state.disconnect_flag.load()) {
        for (int i = 0; i < ping_seconds && !stop_event.is_set() && !state.disconnect_flag.load();
             i++) {
            stop_event.wait_for(std::chrono::seconds(1));
        }
        if (stop_event.is_set() || state.disconnect_flag.load()) break;

        try {
            std::lock_guard<std::mutex> lock(*state.write_lock);
            write_message(fd, iso_codec::build_0800(), framing);
            stats.record_sent();
        } catch (const std::exception& e) {
            LOG_WARNING(std::string("upstream_host: keepalive send failed: ") + e.what());
            state.disconnect_flag = true;
            break;
        }
    }
}

void connect_loop(SessionState& state, const RouterConfig& cfg, StopEvent& stop_event, Stats& stats) {
    UpstreamClient client(cfg.upstream);
    auto should_stop = [&] { return stop_event.is_set(); };

    while (!stop_event.is_set()) {
        auto conn_opt = client.connect(should_stop);
        if (!conn_opt) break;
        auto conn = conn_opt.value();

        {
            std::lock_guard<std::mutex> lock(state.conn_mutex);
            state.fd = conn.fd;
            state.write_lock = conn.write_lock;
        }
        state.disconnect_flag = false;
        state.connected = true;
        stats.set_connection("router", true);

        try {
            std::lock_guard<std::mutex> lock(*conn.write_lock);
            write_message(conn.fd, iso_codec::build_0800(), cfg.upstream.framing);
            stats.record_sent();
        } catch (const std::exception& e) {
            LOG_WARNING(std::string("upstream_host: initial keepalive failed: ") + e.what());
        }

        std::thread keepalive(keepalive_loop, std::ref(state), conn.fd,
                              std::cref(cfg.upstream.framing), cfg.upstream.ping_0800_seconds,
                              std::ref(stop_event), std::ref(stats));

        receive_loop(state, conn.fd, cfg.upstream.framing, stats);

        state.disconnect_flag = true;  // wakes the keepalive loop promptly if it isn't dead already
        if (keepalive.joinable()) keepalive.join();

        {
            std::lock_guard<std::mutex> lock(state.conn_mutex);
            state.fd = -1;
            state.write_lock.reset();
        }
        state.connected = false;
        stats.set_connection("router", false);
        ::shutdown(conn.fd, SHUT_RDWR);
        ::close(conn.fd);
    }
}

void send_loop(SessionState& state, const RouterConfig& cfg, StopEvent& stop_event, Stats& stats,
              std::vector<std::map<std::string, std::string>> rows,
              std::optional<double> rate, std::optional<double> duration_seconds) {
    auto interval = std::chrono::milliseconds(
        rate && *rate > 0 ? static_cast<long long>(std::round(1000.0 / *rate)) : 20);
    std::optional<std::chrono::steady_clock::time_point> deadline;
    if (duration_seconds) {
        deadline = std::chrono::steady_clock::now() +
                   std::chrono::milliseconds(static_cast<long long>(*duration_seconds * 1000));
    }

    // No duration: legacy one-pass-through-the-CSV functional-test behavior. With a duration:
    // cycle the (usually tiny) CSV rows to sustain load for the requested window - used by
    // stress_run.sh.
    size_t idx = 0;
    while (!stop_event.is_set() && !rows.empty()) {
        if (idx >= rows.size()) {
            if (!deadline) break;
            idx = 0;
        }
        if (deadline && std::chrono::steady_clock::now() >= *deadline) break;
        auto& row = rows[idx++];

        int fd;
        std::shared_ptr<std::mutex> write_lock;
        {
            std::lock_guard<std::mutex> lock(state.conn_mutex);
            fd = state.fd;
            write_lock = state.write_lock;
        }
        if (fd < 0 || !write_lock) break;

        std::string stan = next_stan(state.stan_counter);
        {
            std::lock_guard<std::mutex> lock(state.pending_mutex);
            state.pending[stan] = row;
        }
        {
            std::lock_guard<std::mutex> lock(state.send_times_mutex);
            state.send_times[stan] = std::chrono::steady_clock::now();
        }

        auto msg = row;
        msg["t"] = "0100";
        msg["11"] = stan;

        try {
            auto encoded = iso_codec::encode(msg);
            std::lock_guard<std::mutex> lock(*write_lock);
            write_message(fd, encoded, cfg.upstream.framing);
            stats.record_sent();
            state.run_sent.fetch_add(1);
        } catch (const std::exception& e) {
            LOG_WARNING(std::string("upstream_host: send loop write failed: ") + e.what());
            break;
        }

        std::this_thread::sleep_for(interval);
    }
    // Marks when active sending stopped, distinct from "now" - /stress_stats is queried after a
    // trailing grace window (letting in-flight responses land), and achieved_tps must reflect
    // the actual send window, not that grace window too.
    state.run_end_ms = now_ms();
    state.sending = false;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        auto cfg_path = parse_config_arg(argc, argv);
        auto cfg = RouterConfig::from_file(cfg_path);

        std::filesystem::create_directories(kInputDir);

        StopEvent stop_event;
        Stats stats(cfg.yellow_threshold_seconds);
        Logger::instance().set_level(*parse_log_level(cfg.log_level));

        SessionState state;

        CommandServer cmd(cfg.upstream.command_port, stats, stop_event, "0.0.0.0", {});

        cmd.register_route(
            "/upload", {"POST"}, /*protected=*/false,
            [&](const httplib::Request& req, httplib::Response& res) {
                if (!req.has_file("file")) {
                    send_json(res, 400, {{"error", "missing 'file' part"}});
                    return;
                }
                auto file = req.get_file_value("file");
                std::ofstream out(kInputDir + "/" + kCsvFilename,
                                  std::ios::binary | std::ios::trunc);
                out << file.content;
                send_json(res, 200, {{"status", "uploaded"}});
            });

        cmd.register_route(
            "/start", {"GET"}, /*protected=*/false,
            [&](const httplib::Request& req, httplib::Response& res) {
                if (!state.connected.load()) {
                    send_json(res, 503, {{"error", "no live connection to router"}});
                    return;
                }
                bool expected = false;
                if (!state.sending.compare_exchange_strong(expected, true)) {
                    send_json(res, 409, {{"error", "send already in progress"}});
                    return;
                }

                std::vector<std::map<std::string, std::string>> rows;
                try {
                    rows = parse_csv(kInputDir + "/" + kCsvFilename);
                } catch (const std::exception& e) {
                    state.sending = false;
                    send_json(res, 400, {{"error", e.what()}});
                    return;
                }

                // rate/duration are optional: omitted, this is the original
                // one-pass-through-the-CSV functional-test behavior at the legacy fixed 20ms
                // pacing. Given, send_loop instead cycles the CSV rows at 1/rate intervals until
                // duration elapses - used by stress_run.sh, not by the functional run_test.sh.
                std::optional<double> rate, duration;
                if (req.has_param("rate")) rate = std::stod(req.get_param_value("rate"));
                if (req.has_param("duration")) duration = std::stod(req.get_param_value("duration"));

                {
                    std::lock_guard<std::mutex> lock(state.pending_mutex);
                    state.pending.clear();
                }
                {
                    std::lock_guard<std::mutex> lock(state.send_times_mutex);
                    state.send_times.clear();
                }
                {
                    std::lock_guard<std::mutex> lock(state.results_mutex);
                    state.results.clear();
                }
                {
                    std::lock_guard<std::mutex> lock(state.latencies_mutex);
                    state.latencies_ms.clear();
                }
                state.run_start_ms = now_ms();
                state.run_end_ms = 0;
                state.run_sent = 0;

                {
                    std::lock_guard<std::mutex> lock(state.send_mutex);
                    if (state.send_thread.joinable()) state.send_thread.join();
                    state.send_thread = std::thread(send_loop, std::ref(state), std::cref(cfg),
                                                    std::ref(stop_event), std::ref(stats), rows,
                                                    rate, duration);
                }
                send_json(res, 200, {{"rows", rows.size()}});
            });

        cmd.register_route(
            "/results", {"GET"}, /*protected=*/false,
            [&](const httplib::Request&, httplib::Response& res) {
                json arr = json::array();
                {
                    std::lock_guard<std::mutex> lock(state.results_mutex);
                    for (const auto& r : state.results) arr.push_back(r);
                }
                send_json(res, 200, arr);
            });

        cmd.register_route(
            "/stress_stats", {"GET"}, /*protected=*/false,
            [&](const httplib::Request&, httplib::Response& res) {
                int received;
                {
                    std::lock_guard<std::mutex> lock(state.results_mutex);
                    received = static_cast<int>(state.results.size());
                }
                int sent = state.run_sent.load();
                long long end_ms = state.run_end_ms.load();
                if (end_ms == 0) end_ms = now_ms();
                long long start_ms = state.run_start_ms.load();
                double elapsed_s = start_ms > 0 ? (end_ms - start_ms) / 1000.0 : 0.0;

                std::vector<double> samples;
                {
                    std::lock_guard<std::mutex> lock(state.latencies_mutex);
                    samples = state.latencies_ms;
                }
                std::sort(samples.begin(), samples.end());

                auto percentile = [&](double p) -> json {
                    if (samples.empty()) return nullptr;
                    size_t idx = std::min(samples.size() - 1,
                        static_cast<size_t>(std::llround(p / 100.0 * (samples.size() - 1))));
                    return std::round(samples[idx] * 100.0) / 100.0;
                };

                json body;
                body["sent"] = sent;
                body["received"] = received;
                body["errors"] = std::max(0, sent - received);
                body["elapsed_s"] = std::round(elapsed_s * 100.0) / 100.0;
                body["achieved_tps"] = elapsed_s > 0 ? std::round(sent / elapsed_s * 100.0) / 100.0 : 0;
                body["p50_ms"] = percentile(50);
                body["p95_ms"] = percentile(95);
                body["p99_ms"] = percentile(99);
                body["max_ms"] = samples.empty() ? json(nullptr)
                                                  : json(std::round(samples.back() * 100.0) / 100.0);
                send_json(res, 200, body);
            });

        cmd.start();

        std::thread connect_thread(connect_loop, std::ref(state), std::cref(cfg),
                                   std::ref(stop_event), std::ref(stats));

        LOG_INFO("upstream_host connecting to " + cfg.upstream.host + ":" +
                 std::to_string(cfg.upstream.port));

        while (!stop_event.is_set()) {
            stop_event.wait_for(std::chrono::seconds(1));
        }

        // Force the live socket closed so a blocked receive_loop read unblocks promptly instead
        // of holding up shutdown until the router side happens to close it.
        {
            std::lock_guard<std::mutex> lock(state.conn_mutex);
            if (state.fd >= 0) ::shutdown(state.fd, SHUT_RDWR);
        }

        if (connect_thread.joinable()) connect_thread.join();
        {
            std::lock_guard<std::mutex> lock(state.send_mutex);
            if (state.send_thread.joinable()) state.send_thread.join();
        }

        cmd.stop();
        return 0;
    } catch (const std::exception& e) {
        LOG_ERROR(std::string("fatal: ") + e.what());
        return 1;
    }
}

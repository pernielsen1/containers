#include <sys/socket.h>

#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <filesystem>
#include <fstream>
#include <map>
#include <memory>
#include <mutex>
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
};

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
              std::vector<std::map<std::string, std::string>> rows) {
    for (auto& row : rows) {
        if (stop_event.is_set()) break;

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

        auto msg = row;
        msg["t"] = "0100";
        msg["11"] = stan;

        try {
            auto encoded = iso_codec::encode(msg);
            std::lock_guard<std::mutex> lock(*write_lock);
            write_message(fd, encoded, cfg.upstream.framing);
            stats.record_sent();
        } catch (const std::exception& e) {
            LOG_WARNING(std::string("upstream_host: send loop write failed: ") + e.what());
            break;
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
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
            [&](const httplib::Request&, httplib::Response& res) {
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

                {
                    std::lock_guard<std::mutex> lock(state.send_mutex);
                    if (state.send_thread.joinable()) state.send_thread.join();
                    state.send_thread = std::thread(send_loop, std::ref(state), std::cref(cfg),
                                                    std::ref(stop_event), std::ref(stats), rows);
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

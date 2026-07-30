#include <arpa/inet.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <atomic>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <exception>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <thread>
#include <vector>

#include <nlohmann/json.hpp>

#include "router/router_config.h"
#include "shared/command_server.h"
#include "shared/ebcdic.h"
#include "shared/ims_connect.h"
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

// Bounded blocking queue of raw response frames awaiting delivery on a from-conn -- mirrors the
// dispatcher's own queue shape (deque + mutex + condition_variable).
class ResponseQueue {
public:
    explicit ResponseQueue(size_t max_size) : max_size_(max_size) {}

    void push(std::vector<uint8_t> item) {
        std::unique_lock<std::mutex> lock(mutex_);
        cv_not_full_.wait(lock, [this] { return queue_.size() < max_size_; });
        queue_.push_back(std::move(item));
        cv_not_empty_.notify_one();
    }

    std::optional<std::vector<uint8_t>> pop_wait(std::chrono::milliseconds timeout) {
        std::unique_lock<std::mutex> lock(mutex_);
        if (!cv_not_empty_.wait_for(lock, timeout, [this] { return !queue_.empty(); })) {
            return std::nullopt;
        }
        auto item = std::move(queue_.front());
        queue_.pop_front();
        cv_not_full_.notify_one();
        return item;
    }

private:
    size_t max_size_;
    std::mutex mutex_;
    std::condition_variable cv_not_empty_;
    std::condition_variable cv_not_full_;
    std::deque<std::vector<uint8_t>> queue_;
};

// Maps a session's client_id (raw bytes, used as an opaque string key) to its from-conn's queue --
// registered once the from-conn identifies itself, looked up by the to-conn when routing frames.
class ConnectionRegistry {
public:
    std::shared_ptr<ResponseQueue> register_from_conn(const std::string& client_key, int queue_maxsize) {
        auto q = std::make_shared<ResponseQueue>(static_cast<size_t>(queue_maxsize));
        std::lock_guard<std::mutex> lock(mutex_);
        queues_[client_key] = q;
        return q;
    }

    void unregister(const std::string& client_key) {
        std::lock_guard<std::mutex> lock(mutex_);
        queues_.erase(client_key);
    }

    // Polls up to `timeout` for the from-conn's queue to exist -- covers the startup race where
    // the to-conn's first frame (the pipe-cleaner ping) can arrive before the from-conn's
    // resume-TPIPE has been processed.
    std::shared_ptr<ResponseQueue> wait_for(const std::string& client_key,
                                            std::chrono::milliseconds timeout) {
        auto deadline = std::chrono::steady_clock::now() + timeout;
        while (true) {
            {
                std::lock_guard<std::mutex> lock(mutex_);
                auto it = queues_.find(client_key);
                if (it != queues_.end()) return it->second;
            }
            if (std::chrono::steady_clock::now() >= deadline) return nullptr;
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }
    }

private:
    std::mutex mutex_;
    std::map<std::string, std::shared_ptr<ResponseQueue>> queues_;
};

std::string next_auth_code() {
    static std::atomic<int> counter{0};
    int next = (counter.fetch_add(1) + 1) % 1'000'000;
    char buf[8];
    std::snprintf(buf, sizeof(buf), "%06d", next);
    return std::string(buf);
}

std::map<std::string, std::string> process_0100(const std::map<std::string, std::string>& req,
                                                 const std::map<std::string, PanRecord>& pans) {
    auto resp = req;
    resp["t"] = "0110";

    std::string pan = req.count("2") ? req.at("2") : std::string("");
    std::string f47_str = req.count("47") ? req.at("47") : std::string("");
    json f47 = iso_codec::f47_decode(f47_str);

    std::string rc;
    if (!pans.count(pan)) {
        rc = "01";
    } else if (f47.value("response_code", std::string("00")) != "00") {
        rc = "01";
    } else {
        rc = "00";
        resp["38"] = next_auth_code();
    }

    resp["39"] = rc;
    f47["message_type"] = "0110";
    f47["response_code"] = rc;
    resp["47"] = iso_codec::f47_encode(f47);
    return resp;
}

void route_frame(const std::string& client_key, const std::vector<uint8_t>& transcode,
                 const std::vector<uint8_t>& iso_data, ConnectionRegistry& registry,
                 const std::map<std::string, PanRecord>& pans, Stats& stats) {
    auto queue = registry.wait_for(client_key, std::chrono::seconds(2));
    if (!queue) {
        LOG_WARNING("downstream_host: no from-conn registered for client, dropping frame");
        return;
    }

    if (transcode == PING_TRANSCODE) {
        auto marker = to_ebcdic("PING", 4);
        auto tail = to_ebcdic("PIPES cleaned", 13);
        marker.insert(marker.end(), tail.begin(), tail.end());
        queue->push(std::move(marker));
        return;
    }

    if (iso_data.empty()) return;

    auto req = iso_codec::decode(iso_data);
    stats.record_recv();
    std::string mti = req.at("t");

    if (mti == "0800") {
        std::string f24 = req.count("24") ? req.at("24") : std::string("");
        queue->push(iso_codec::build_0810(f24));
    } else if (mti == "0120") {
        auto resp = req;
        resp["t"] = "0130";
        resp["39"] = "00";
        queue->push(iso_codec::encode(resp));
    } else if (mti == "0420") {
        auto resp = req;
        resp["t"] = "0430";
        resp["39"] = "00";
        queue->push(iso_codec::encode(resp));
    } else if (mti == "0100") {
        queue->push(iso_codec::encode(process_0100(req, pans)));
    } else {
        LOG_WARNING("downstream_host: unknown mti=" + mti);
        return;
    }
    stats.record_sent();
}

void handle_from_conn(int fd, std::shared_ptr<ResponseQueue> queue, StopEvent& stop_event) {
    while (!stop_event.is_set()) {
        auto item = queue->pop_wait(std::chrono::seconds(1));
        if (!item) continue;
        try {
            write_response(fd, *item);
        } catch (const std::exception& e) {
            LOG_WARNING(std::string("downstream_host: from-conn write failed: ") + e.what());
            break;
        }
    }
    ::shutdown(fd, SHUT_RDWR);
    ::close(fd);
}

void handle_to_conn(int fd, ConnectionRegistry& registry, const std::map<std::string, PanRecord>& pans,
                    Stats& stats, const ImsRequest& first_req) {
    try {
        std::string key(first_req.client_id.begin(), first_req.client_id.end());
        route_frame(key, first_req.transcode, first_req.iso_data, registry, pans, stats);
        while (true) {
            auto req = read_request(fd);
            std::string req_key(req.client_id.begin(), req.client_id.end());
            route_frame(req_key, req.transcode, req.iso_data, registry, pans, stats);
        }
    } catch (const std::exception& e) {
        LOG_INFO(std::string("downstream_host: to-conn closed: ") + e.what());
    }
    ::shutdown(fd, SHUT_RDWR);
    ::close(fd);
}

void handle_connection(int fd, ConnectionRegistry* registry, const std::map<std::string, PanRecord>* pans,
                       int queue_maxsize, StopEvent* stop_event, Stats* stats) {
    ImsRequest req;
    try {
        req = read_request(fd);
    } catch (const std::exception&) {
        ::close(fd);
        return;
    }
    std::string client_key(req.client_id.begin(), req.client_id.end());

    if (req.irm_f0 == 0x80) {
        auto queue = registry->register_from_conn(client_key, queue_maxsize);
        stats->set_connection("downstream_from", true);
        handle_from_conn(fd, queue, *stop_event);
        registry->unregister(client_key);
        stats->set_connection("downstream_from", false);
    } else {
        stats->set_connection("downstream_to", true);
        handle_to_conn(fd, *registry, *pans, *stats, req);
        stats->set_connection("downstream_to", false);
    }
}

int create_listen_socket(int port) {
    int fd = ::socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) throw std::runtime_error("socket() failed");
    int opt = 1;
    ::setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(static_cast<uint16_t>(port));
    addr.sin_addr.s_addr = INADDR_ANY;

    if (::bind(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
        ::close(fd);
        throw std::runtime_error(std::string("bind() failed: ") + std::strerror(errno));
    }
    if (::listen(fd, 16) < 0) {
        ::close(fd);
        throw std::runtime_error(std::string("listen() failed: ") + std::strerror(errno));
    }
    return fd;
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

        CommandServer cmd(cfg.downstream.command_port, stats, stop_event, "0.0.0.0", {});
        cmd.start();

        ConnectionRegistry registry;
        int listen_fd = create_listen_socket(cfg.downstream.port);
        LOG_INFO("downstream_host listening on port " + std::to_string(cfg.downstream.port));

        std::vector<std::thread> conn_threads;
        std::mutex active_fds_mutex;
        std::vector<int> active_fds;

        while (!stop_event.is_set()) {
            pollfd pfd{listen_fd, POLLIN, 0};
            int rc = ::poll(&pfd, 1, 1000);
            if (rc <= 0) continue;

            int client_fd = ::accept(listen_fd, nullptr, nullptr);
            if (client_fd < 0) continue;

            {
                std::lock_guard<std::mutex> lock(active_fds_mutex);
                active_fds.push_back(client_fd);
            }
            conn_threads.emplace_back(handle_connection, client_fd, &registry, &pans,
                                      cfg.queue_maxsize, &stop_event, &stats);
        }

        ::close(listen_fd);
        cmd.stop();

        // The to-conn loop only checks the stop event between frames, and can otherwise block
        // forever in a blocking read; force every live socket closed so pending reads/writes
        // unblock and the session threads below can actually be joined.
        {
            std::lock_guard<std::mutex> lock(active_fds_mutex);
            for (int fd : active_fds) {
                ::shutdown(fd, SHUT_RDWR);
            }
        }

        for (auto& t : conn_threads) {
            if (t.joinable()) t.join();
        }
        return 0;
    } catch (const std::exception& e) {
        LOG_ERROR(std::string("fatal: ") + e.what());
        return 1;
    }
}

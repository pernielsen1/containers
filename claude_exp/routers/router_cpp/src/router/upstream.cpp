#include "router/upstream.h"

#include <arpa/inet.h>
#include <fcntl.h>
#include <netdb.h>
#include <netinet/in.h>
#include <poll.h>
#include <unistd.h>

#include <cerrno>
#include <chrono>
#include <cstring>
#include <stdexcept>
#include <thread>

#include "shared/log.h"
#include "shared/tls.h"

namespace router {

namespace {

std::runtime_error errno_error(const std::string& what) {
    return std::runtime_error(what + ": " + std::strerror(errno));
}

std::string format_addr(const sockaddr_storage& storage) {
    const auto* addr_in = reinterpret_cast<const sockaddr_in*>(&storage);
    char buf[INET_ADDRSTRLEN] = {};
    ::inet_ntop(AF_INET, &addr_in->sin_addr, buf, sizeof(buf));
    return std::string(buf) + ":" + std::to_string(ntohs(addr_in->sin_port));
}

}  // namespace

UpstreamServer::UpstreamServer(const UpstreamConfig& cfg) : cfg_(cfg) {
    listen_fd_ = ::socket(AF_INET, SOCK_STREAM, 0);
    if (listen_fd_ < 0) throw errno_error("socket() failed");

    int opt = 1;
    ::setsockopt(listen_fd_, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(static_cast<uint16_t>(cfg.port));

    if (::bind(listen_fd_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
        auto err = errno_error("bind() failed");
        ::close(listen_fd_);
        throw err;
    }
    if (::listen(listen_fd_, 16) < 0) {
        auto err = errno_error("listen() failed");
        ::close(listen_fd_);
        throw err;
    }
    LOG_INFO("upstream server listening on port " + std::to_string(cfg.port));
}

UpstreamServer::~UpstreamServer() {
    if (listen_fd_ >= 0) ::close(listen_fd_);
}

std::optional<UpstreamConn> UpstreamServer::accept(const std::function<bool()>& should_stop) {
    while (!should_stop()) {
        pollfd pfd{listen_fd_, POLLIN, 0};
        int rc = ::poll(&pfd, 1, 1000);
        if (rc < 0) {
            if (errno == EINTR) continue;
            return std::nullopt;
        }
        if (rc == 0) continue;  // timeout: recheck should_stop

        sockaddr_storage peer{};
        socklen_t peer_len = sizeof(peer);
        int fd = ::accept(listen_fd_, reinterpret_cast<sockaddr*>(&peer), &peer_len);
        if (fd < 0) {
            if (errno == EINTR) continue;
            return std::nullopt;
        }

        if (cfg_.ssl_active) {
            try {
                shared::tls::wrap_server(fd, cfg_.certfile, cfg_.keyfile, cfg_.cafile);
            } catch (const std::exception& e) {
                LOG_WARNING(std::string("upstream TLS handshake failed: ") + e.what());
                ::close(fd);
                continue;
            }
        }

        UpstreamConn conn;
        conn.fd = fd;
        conn.addr = peer;
        conn.write_lock = std::make_shared<std::mutex>();
        LOG_INFO("upstream connected from " + format_addr(peer));
        return conn;
    }
    return std::nullopt;
}

UpstreamClient::UpstreamClient(UpstreamConfig cfg) : cfg_(std::move(cfg)) {}

bool UpstreamClient::wait_retry(const std::function<bool()>& should_stop) const {
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(cfg_.retry_seconds);
    while (std::chrono::steady_clock::now() < deadline) {
        if (should_stop()) return false;
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
    }
    return !should_stop();
}

std::optional<UpstreamConn> UpstreamClient::connect(const std::function<bool()>& should_stop) {
    while (!should_stop()) {
        int fd = ::socket(AF_INET, SOCK_STREAM, 0);
        if (fd < 0) {
            if (!wait_retry(should_stop)) return std::nullopt;
            continue;
        }

        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_port = htons(static_cast<uint16_t>(cfg_.port));

        bool resolved = ::inet_pton(AF_INET, cfg_.host.c_str(), &addr.sin_addr) == 1;
        if (!resolved) {
            addrinfo hints{};
            hints.ai_family = AF_INET;
            hints.ai_socktype = SOCK_STREAM;
            addrinfo* res = nullptr;
            std::string port_str = std::to_string(cfg_.port);
            if (::getaddrinfo(cfg_.host.c_str(), port_str.c_str(), &hints, &res) == 0 && res != nullptr) {
                std::memcpy(&addr, res->ai_addr, sizeof(sockaddr_in));
                ::freeaddrinfo(res);
                resolved = true;
            }
        }
        if (!resolved) {
            ::close(fd);
            if (!wait_retry(should_stop)) return std::nullopt;
            continue;
        }

        int flags = ::fcntl(fd, F_GETFL, 0);
        ::fcntl(fd, F_SETFL, flags | O_NONBLOCK);

        int rc = ::connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr));
        bool connected = (rc == 0);
        if (rc < 0 && errno == EINPROGRESS) {
            pollfd pfd{fd, POLLOUT, 0};
            int prc = ::poll(&pfd, 1, 5000);
            if (prc > 0) {
                int so_error = 0;
                socklen_t len = sizeof(so_error);
                ::getsockopt(fd, SOL_SOCKET, SO_ERROR, &so_error, &len);
                connected = (so_error == 0);
            }
        }

        if (!connected) {
            ::close(fd);
            if (!wait_retry(should_stop)) return std::nullopt;
            continue;
        }

        // Restore blocking mode -- the connect-timeout must not leak onto subsequent reads.
        ::fcntl(fd, F_SETFL, flags);

        if (cfg_.ssl_active) {
            try {
                shared::tls::wrap_client(fd, cfg_.certfile, cfg_.keyfile, cfg_.cafile, cfg_.host);
            } catch (const std::exception& e) {
                LOG_WARNING(std::string("upstream TLS handshake failed: ") + e.what());
                ::close(fd);
                if (!wait_retry(should_stop)) return std::nullopt;
                continue;
            }
        }

        UpstreamConn conn;
        conn.fd = fd;
        std::memcpy(&conn.addr, &addr, sizeof(sockaddr_in));
        conn.write_lock = std::make_shared<std::mutex>();
        LOG_INFO("connected to upstream at " + format_addr(conn.addr));
        return conn;
    }
    return std::nullopt;
}

}  // namespace router

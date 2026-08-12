#include "router/downstream_connection.h"

#include <arpa/inet.h>
#include <fcntl.h>
#include <netdb.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <cerrno>
#include <cstring>
#include <stdexcept>

#include "shared/ebcdic.h"
#include "shared/framing.h"
#include "shared/ims_connect.h"
#include "shared/log.h"
#include "shared/tls.h"

namespace xv6::router {

namespace {

std::runtime_error errno_error(const std::string& what) {
    return std::runtime_error(what + ": " + std::strerror(errno));
}

int connect_with_timeout(const std::string& host, int port, int timeout_ms) {
    int fd = ::socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) throw errno_error("socket() failed");

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(static_cast<uint16_t>(port));

    bool resolved = ::inet_pton(AF_INET, host.c_str(), &addr.sin_addr) == 1;
    if (!resolved) {
        addrinfo hints{};
        hints.ai_family = AF_INET;
        hints.ai_socktype = SOCK_STREAM;
        addrinfo* res = nullptr;
        std::string port_str = std::to_string(port);
        if (::getaddrinfo(host.c_str(), port_str.c_str(), &hints, &res) == 0 && res != nullptr) {
            std::memcpy(&addr, res->ai_addr, sizeof(sockaddr_in));
            ::freeaddrinfo(res);
            resolved = true;
        }
    }
    if (!resolved) {
        ::close(fd);
        throw std::runtime_error("failed to resolve host: " + host);
    }

    int flags = ::fcntl(fd, F_GETFL, 0);
    ::fcntl(fd, F_SETFL, flags | O_NONBLOCK);

    int rc = ::connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr));
    bool connected = (rc == 0);
    if (rc < 0 && errno == EINPROGRESS) {
        pollfd pfd{fd, POLLOUT, 0};
        int prc = ::poll(&pfd, 1, timeout_ms);
        if (prc > 0) {
            int so_error = 0;
            socklen_t len = sizeof(so_error);
            ::getsockopt(fd, SOL_SOCKET, SO_ERROR, &so_error, &len);
            connected = (so_error == 0);
        }
    }
    if (!connected) {
        ::close(fd);
        throw std::runtime_error("connect() to " + host + ":" + std::to_string(port) +
                                  " failed or timed out");
    }

    // The 5s value passed above is connect-only; restore blocking mode explicitly, or every
    // subsequent blocking read on this socket would incorrectly time out after 5s of idle.
    ::fcntl(fd, F_SETFL, flags);
    return fd;
}

}  // namespace

DownstreamConnection DownstreamConnection::connect(const DownstreamConfig& cfg) {
    int to_fd = connect_with_timeout(cfg.host, cfg.port, 5000);
    int from_fd = -1;
    try {
        from_fd = connect_with_timeout(cfg.host, cfg.port, 5000);
    } catch (...) {
        ::close(to_fd);
        throw;
    }

    if (cfg.ssl_active) {
        try {
            xv6::shared::tls::wrap_client(to_fd, cfg.certfile, cfg.keyfile, cfg.cafile, cfg.host);
            xv6::shared::tls::wrap_client(from_fd, cfg.certfile, cfg.keyfile, cfg.cafile, cfg.host);
        } catch (...) {
            ::close(to_fd);
            ::close(from_fd);
            throw;
        }
    }

    try {
        auto resume = xv6::shared::build_frame(0x80, cfg.irm_id, cfg.client_id, "", {});
        xv6::shared::send_exact(from_fd, resume);

        auto ping_data = xv6::shared::to_ebcdic("1234 clean the pipes", 20);
        auto ping = xv6::shared::build_frame(0x00, cfg.irm_id, cfg.client_id, "", ping_data,
                                              xv6::shared::PING_TRANSCODE);
        xv6::shared::send_exact(to_fd, ping);
    } catch (...) {
        ::close(to_fd);
        ::close(from_fd);
        throw;
    }

    DownstreamConnection conn;
    conn.to_fd_ = to_fd;
    conn.from_fd_ = from_fd;
    LOG_INFO("downstream connected to " + cfg.host + ":" + std::to_string(cfg.port));
    return conn;
}

DownstreamConnection::DownstreamConnection(DownstreamConnection&& other) noexcept
    : to_fd_(other.to_fd_), from_fd_(other.from_fd_), write_mutex_(std::move(other.write_mutex_)) {
    other.to_fd_ = -1;
    other.from_fd_ = -1;
}

DownstreamConnection& DownstreamConnection::operator=(DownstreamConnection&& other) noexcept {
    if (this != &other) {
        close();
        to_fd_ = other.to_fd_;
        from_fd_ = other.from_fd_;
        write_mutex_ = std::move(other.write_mutex_);
        other.to_fd_ = -1;
        other.from_fd_ = -1;
    }
    return *this;
}

DownstreamConnection::~DownstreamConnection() { close(); }

void DownstreamConnection::send(const std::vector<uint8_t>& frame) {
    std::lock_guard<std::mutex> lock(*write_mutex_);
    xv6::shared::send_exact(to_fd_, frame);
}

std::vector<uint8_t> DownstreamConnection::recv() { return xv6::shared::read_response(from_fd_); }

void DownstreamConnection::close() {
    if (to_fd_ >= 0) {
        ::shutdown(to_fd_, SHUT_RDWR);
        xv6::shared::tls::close(to_fd_);
        ::close(to_fd_);
        to_fd_ = -1;
    }
    if (from_fd_ >= 0) {
        ::shutdown(from_fd_, SHUT_RDWR);
        xv6::shared::tls::close(from_fd_);
        ::close(from_fd_);
        from_fd_ = -1;
    }
}

}  // namespace xv6::router

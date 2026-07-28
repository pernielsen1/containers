#pragma once

#include <cstdint>
#include <memory>
#include <mutex>
#include <vector>

#include "router/router_config.h"

namespace xv6::router {

// Dual-socket IMS session: one socket sends requests (to-socket), one receives responses
// (from-socket).
class DownstreamConnection {
public:
    static DownstreamConnection connect(const DownstreamConfig& cfg);

    DownstreamConnection(DownstreamConnection&& other) noexcept;
    DownstreamConnection& operator=(DownstreamConnection&& other) noexcept;
    DownstreamConnection(const DownstreamConnection&) = delete;
    DownstreamConnection& operator=(const DownstreamConnection&) = delete;
    ~DownstreamConnection();

    void send(const std::vector<uint8_t>& frame);   // acquires the write mutex, writes to to_fd
    std::vector<uint8_t> recv();                       // blocking read from from_fd
    // shutdown(SHUT_RDWR) then close() on both fds -- unblocks any thread parked in recv().
    // Idempotent; safe to call more than once (including implicitly via the destructor).
    void close();

private:
    DownstreamConnection() = default;

    int to_fd_ = -1;
    int from_fd_ = -1;
    std::unique_ptr<std::mutex> write_mutex_ = std::make_unique<std::mutex>();
};

}  // namespace xv6::router

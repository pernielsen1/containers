#include "router/router_session.h"

#include <algorithm>
#include <cstring>
#include <exception>
#include <sys/socket.h>

#include "shared/ebcdic.h"
#include "shared/framing.h"
#include "shared/ims_connect.h"
#include "shared/iso_codec.h"
#include "shared/log.h"
#include "shared/tls.h"

using namespace router;
using namespace shared;

std::unique_ptr<RouterSession> RouterSession::connect(const RouterConfig& cfg, Stats& stats,
                                                       StopEvent& stop_event) {
    DownstreamConnection downstream = DownstreamConnection::connect(cfg.downstream);
    stats.set_connection("downstream", true);

    auto crypto = std::make_unique<CryptoClient>(cfg.crypto, cfg.crypto_breaker_threshold,
                                                  cfg.crypto_breaker_cooldown_seconds);
    auto reconnect_event = std::make_unique<StopEvent>();

    // new, not std::make_unique: the constructor is private, and make_unique -- being a free
    // function, not a member or friend of RouterSession -- can't reach it.
    return std::unique_ptr<RouterSession>(
        new RouterSession(cfg, std::move(downstream), std::move(crypto), stats, stop_event,
                          std::move(reconnect_event)));
}

RouterSession::RouterSession(const RouterConfig& cfg, DownstreamConnection&& downstream,
                              std::unique_ptr<CryptoClient> crypto, Stats& stats,
                              StopEvent& stop_event, std::unique_ptr<StopEvent>&& reconnect_event)
    : cfg_(cfg),
      downstream_(std::move(downstream)),
      crypto_(std::move(crypto)),
      dispatcher_(std::make_unique<Dispatcher>(cfg, downstream_, *crypto_, stats, *reconnect_event)),
      stats_(stats),
      stop_event_(stop_event),
      reconnect_event_(std::move(reconnect_event)) {}

Dispatcher* RouterSession::dispatcher() {
    return dispatcher_.get();
}

void RouterSession::run_until_disconnect(UpstreamServer* srv_sock) {
    dispatcher_->start();

    ds_receiver_thread_ = std::thread(&RouterSession::downstream_receiver, this);

    std::thread up_thread;
    if (cfg_.upstream.mode == "server") {
        up_thread = std::thread([this, srv_sock] {
            auto should_stop = [this] {
                return stop_event_.is_set() || reconnect_event_->is_set();
            };
            while (!should_stop()) {
                auto conn_opt = srv_sock->accept(should_stop);
                if (!conn_opt) break;

                auto conn = conn_opt.value();
                handle_upstream(conn.fd, conn.addr, conn.write_lock);
            }
        });
    } else {
        up_thread = std::thread([this] {
            auto should_stop = [this] {
                return stop_event_.is_set() || reconnect_event_->is_set();
            };
            UpstreamClient client(cfg_.upstream);
            while (!should_stop()) {
                auto conn_opt = client.connect(should_stop);
                if (!conn_opt) break;

                auto conn = conn_opt.value();
                handle_upstream(conn.fd, conn.addr, conn.write_lock);
            }
        });
    }

    while (!stop_event_.is_set() && !reconnect_event_->is_set()) {
        stop_event_.wait_for(std::chrono::seconds(1));
    }

    teardown(up_thread);
}

void RouterSession::handle_upstream(int fd, const sockaddr_storage& addr,
                                     const std::shared_ptr<std::mutex>& write_lock) {
    {
        std::lock_guard lock(*upstream_ref_mutex_);
        upstream_fd_ = fd;
        upstream_write_lock_ = write_lock;
    }
    stats_.set_connection("upstream", true);

    try {
        while (!stop_event_.is_set() && !reconnect_event_->is_set()) {
            auto frame = read_message(fd, cfg_.upstream.framing);
            auto req = iso_codec::decode(frame, iso_codec::encoding_from_config_string(cfg_.upstream.encoding));
            stats_.record_recv();

            std::string mti = req.at("t");
            LOG_DEBUG("upstream recv mti=" + mti);
            if (mti == "0100" || mti == "0120" || mti == "0420") {
                dispatcher_->submit(RoutedMessage{req, fd, write_lock, addr, frame});
            } else if (mti == "0800") {
                forward_0800(req);
            } else {
                LOG_WARNING("unknown upstream mti=" + mti);
            }
        }
    } catch (const std::exception& e) {
        LOG_WARNING(std::string("upstream read error: ") + e.what());
        reconnect_event_->set();
    }

    {
        std::lock_guard lock(*upstream_ref_mutex_);
        upstream_fd_ = -1;
    }
    stats_.set_connection("upstream", false);
}

void RouterSession::forward_0800(const std::map<std::string, std::string>& req) {
    try {
        auto frame = iso_codec::encode(req);
        auto ims_frame = build_frame(0x00, cfg_.downstream.irm_id,
                                    cfg_.downstream.client_id, "0800", frame);
        downstream_.send(ims_frame);
        stats_.record_sent();
        LOG_DEBUG("forwarded 0800 to downstream");
    } catch (const std::exception& e) {
        LOG_ERROR(std::string("0800 forward error: ") + e.what());
    }
}

void RouterSession::forward_0810(const std::map<std::string, std::string>& resp) {
    {
        std::lock_guard lock(*upstream_ref_mutex_);
        if (upstream_fd_ == -1) {
            LOG_WARNING("0810 with no active upstream");
            return;
        }
    }

    try {
        auto frame = iso_codec::encode(resp, iso_codec::encoding_from_config_string(cfg_.upstream.encoding));
        {
            std::lock_guard lock(*upstream_write_lock_);
            write_message(upstream_fd_, frame, cfg_.upstream.framing);
        }
        stats_.record_sent();
        LOG_DEBUG("forwarded 0810 to upstream");
    } catch (const std::exception& e) {
        LOG_ERROR(std::string("0810 forward error: ") + e.what());
    }
}

void RouterSession::downstream_receiver() {
    try {
        while (!stop_event_.is_set() && !reconnect_event_->is_set()) {
            auto frame = downstream_.recv();

            if (frame.size() >= 4) {
                auto ping_ebcdic = to_ebcdic("PING", 4);
                if (std::equal(frame.begin(), frame.begin() + 4, ping_ebcdic.begin())) {
                    LOG_DEBUG("downstream PING pipe-cleaner received, skipping");
                    continue;
                }
            }

            auto resp = iso_codec::decode(frame);
            stats_.record_recv();
            LOG_DEBUG("downstream recv mti=" + resp.at("t"));

            try {
                if (resp.at("t") == "0810") {
                    forward_0810(resp);
                } else {
                    dispatcher_->submit_response(resp, frame);
                }
            } catch (const std::exception& e) {
                LOG_ERROR("unexpected error dispatching downstream message mti=" + resp.at("t"));
            }
        }
    } catch (const std::exception& e) {
        LOG_WARNING(std::string("downstream read error: ") + e.what());
        stats_.set_connection("downstream", false);
        reconnect_event_->set();
    }
}

void RouterSession::teardown(std::thread& up_thread) {
    dispatcher_->drain_and_stop();

    {
        std::lock_guard lock(*upstream_ref_mutex_);
        if (upstream_fd_ != -1) {
            ::shutdown(upstream_fd_, SHUT_RDWR);
            tls::close(upstream_fd_);
            ::close(upstream_fd_);
            upstream_fd_ = -1;
        }
    }

    downstream_.close();

    if (up_thread.joinable()) {
        up_thread.join();
    }
}

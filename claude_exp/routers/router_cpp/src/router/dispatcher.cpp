#include "router/dispatcher.h"

#include <algorithm>
#include <cmath>
#include <cstdio>

#include "shared/framing.h"
#include "shared/ims_connect.h"
#include "shared/iso_codec.h"
#include "shared/log.h"

namespace router {

Dispatcher::Dispatcher(const RouterConfig& cfg, DownstreamConnection& downstream, CryptoClient& crypto,
                         shared::Stats& stats, shared::StopEvent& reconnect_event)
    : cfg_(cfg), downstream_(downstream), crypto_(crypto), stats_(stats), reconnect_event_(reconnect_event) {}

Dispatcher::~Dispatcher() { drain_and_stop(); }

void Dispatcher::start() {
    for (int i = 0; i < cfg_.worker_threads; ++i) {
        workers_.emplace_back([this] { worker_loop(); });
    }
    for (int i = 0; i < cfg_.response_worker_threads; ++i) {
        response_workers_.emplace_back([this] { response_worker_loop(); });
    }
    reaper_ = std::thread([this] { reaper_loop(); });
}

std::string Dispatcher::next_stan() {
    int next = (stan_counter_.fetch_add(1) + 1) % 1'000'000;
    char buf[8];
    std::snprintf(buf, sizeof(buf), "%06d", next);
    return std::string(buf);
}

void Dispatcher::submit(RoutedMessage msg) {
    std::string mti = msg.req.count("t") ? msg.req.at("t") : "";
    msg.enqueued_at = std::chrono::steady_clock::now();
    std::unique_lock<std::mutex> lock(queue_mutex_);
    queue_cv_not_full_.wait(lock, [this] { return queue_.size() < static_cast<size_t>(cfg_.queue_maxsize); });
    queue_.push_back(std::move(msg));
    stats_.set_gauge("queue_depth", static_cast<int>(queue_.size()));
    queue_cv_not_empty_.notify_one();
    LOG_DEBUG("dispatcher: queued mti=" + mti + " (queue_depth=" + std::to_string(queue_.size()) + ")");
}

void Dispatcher::worker_loop() {
    while (true) {
        std::optional<RoutedMessage> item;
        {
            std::unique_lock<std::mutex> lock(queue_mutex_);
            queue_cv_not_empty_.wait(lock, [this] { return !queue_.empty(); });
            item = std::move(queue_.front());
            queue_.pop_front();
            stats_.set_gauge("queue_depth", static_cast<int>(queue_.size()));
            queue_cv_not_full_.notify_one();
        }
        if (!item.has_value()) break;  // poison pill

        double queue_wait_ms =
            std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - item->enqueued_at).count();
        stats_.record_latency("queue_wait", queue_wait_ms);

        try {
            process(*item);
        } catch (const shared::FramingError& e) {
            LOG_ERROR(std::string("dispatcher worker: downstream write failed: ") + e.what());
            reconnect_event_.set();
        } catch (const std::exception& e) {
            LOG_ERROR(std::string("dispatcher worker: ") + e.what());
        }
    }
}

void Dispatcher::submit_response(std::map<std::string, std::string> resp, std::vector<uint8_t> raw) {
    std::string mti = resp.count("t") ? resp.at("t") : "";
    std::unique_lock<std::mutex> lock(response_queue_mutex_);
    response_queue_cv_not_full_.wait(
        lock, [this] { return response_queue_.size() < static_cast<size_t>(cfg_.queue_maxsize); });
    response_queue_.push_back(ResponseItem{std::move(resp), std::move(raw)});
    stats_.set_gauge("response_queue_depth", static_cast<int>(response_queue_.size()));
    response_queue_cv_not_empty_.notify_one();
    LOG_DEBUG("dispatcher: queued response mti=" + mti +
              " (response_queue_depth=" + std::to_string(response_queue_.size()) + ")");
}

void Dispatcher::response_worker_loop() {
    while (true) {
        std::optional<ResponseItem> item;
        {
            std::unique_lock<std::mutex> lock(response_queue_mutex_);
            response_queue_cv_not_empty_.wait(lock, [this] { return !response_queue_.empty(); });
            item = std::move(response_queue_.front());
            response_queue_.pop_front();
            stats_.set_gauge("response_queue_depth", static_cast<int>(response_queue_.size()));
            response_queue_cv_not_full_.notify_one();
        }
        if (!item.has_value()) break;  // poison pill

        try {
            handle_response(item->resp, item->raw);
        } catch (const std::exception& e) {
            LOG_ERROR(std::string("dispatcher response worker: ") + e.what());
        }
    }
}

void Dispatcher::process(RoutedMessage& msg) {
    auto& req = msg.req;
    std::string mti = req.at("t");
    std::string pan = req.count("2") ? req.at("2") : "";
    std::string upstream_stan = req.count("11") ? req.at("11") : "";

    std::string router_stan = next_stan();
    bool tracing = trace_.start(router_stan, upstream_stan, pan, mti, msg.raw);

    auto fwd = req;
    if (mti == "0100") {
        std::string f47 = req.count("47") ? req.at("47") : "";
        auto crypto_start = std::chrono::steady_clock::now();
        std::string enriched = crypto_.validate("validate_0100", pan, f47, router_stan);
        double crypto_ms =
            std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - crypto_start).count();
        stats_.record_latency("crypto_rtt", crypto_ms);
        if (tracing) {
            trace_.hop(router_stan, "crypto_call", nullptr,
                       {{"crypto_ms", std::round(crypto_ms * 1000.0) / 1000.0}, {"enriched", !enriched.empty()}});
        }
        if (!enriched.empty()) fwd["47"] = enriched;
    }
    fwd["11"] = router_stan;

    auto encoded = shared::iso_codec::encode(fwd);
    if (tracing) {
        trace_.hop(router_stan, "downstream_send", &encoded);
    }

    // msg.enqueued_at defaults to epoch only for tests that build a RoutedMessage without going
    // through submit() (which always stamps it) - fall back to now() in that case, same as
    // router_java's `msg.enqueuedAtNanos() != 0 ? ... : System.nanoTime()`.
    auto started_at = msg.enqueued_at == std::chrono::steady_clock::time_point{}
                           ? std::chrono::steady_clock::now()
                           : msg.enqueued_at;
    {
        std::lock_guard<std::mutex> lock(pending_mutex_);
        if (pending_.find(router_stan) != pending_.end()) {
            LOG_ERROR("dispatcher: router_stan collision on " + router_stan +
                      " -- overwriting a still-outstanding entry");
        }
        pending_[router_stan] =
            PendingEntry{msg.up_fd, msg.up_write_lock, upstream_stan, std::chrono::steady_clock::now(), started_at};
        stats_.set_gauge("pending_count", static_cast<int>(pending_.size()));
    }

    auto frame =
        shared::build_frame(0x00, cfg_.downstream.irm_id, cfg_.downstream.client_id, fwd.at("t"), encoded);
    downstream_.send(frame);
    stats_.record_sent();
    LOG_DEBUG("dispatcher: forwarded mti=" + mti + " to downstream, upstream_stan=" + upstream_stan +
              " router_stan=" + router_stan);
}

void Dispatcher::handle_response(const std::map<std::string, std::string>& resp, const std::vector<uint8_t>& raw) {
    std::string mti = resp.at("t");
    if (mti == "0810") return;
    if (mti != "0110" && mti != "0130" && mti != "0430") {
        LOG_WARNING("dispatcher: unexpected downstream mti=" + mti);
        return;
    }

    std::string router_stan = resp.count("11") ? resp.at("11") : "";
    trace_.hop(router_stan, "downstream_recv", &raw);
    bool tracing = trace_.is_tracing(router_stan);

    auto now = std::chrono::steady_clock::now();
    PendingEntry entry;
    {
        std::lock_guard<std::mutex> lock(pending_mutex_);
        auto it = pending_.find(router_stan);
        if (it == pending_.end()) {
            LOG_WARNING("dispatcher: no pending entry for router_stan=" + router_stan);
            if (tracing) trace_.finish(router_stan);
            return;
        }
        entry = it->second;
        pending_.erase(it);
        stats_.set_gauge("pending_count", static_cast<int>(pending_.size()));
    }
    stats_.record_latency("downstream_rtt",
                          std::chrono::duration<double, std::milli>(now - entry.created_at).count());

    auto fwd = resp;
    fwd["11"] = entry.upstream_stan;

    if (mti == "0110") {
        std::string pan = fwd.count("2") ? fwd.at("2") : "";
        std::string f47 = fwd.count("47") ? fwd.at("47") : "";
        auto crypto_start = std::chrono::steady_clock::now();
        std::string enriched = crypto_.validate("validate_0110", pan, f47, router_stan);
        double crypto_ms =
            std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - crypto_start).count();
        stats_.record_latency("crypto_rtt", crypto_ms);
        if (tracing) {
            trace_.hop(router_stan, "crypto_call", nullptr,
                       {{"crypto_ms", std::round(crypto_ms * 1000.0) / 1000.0}, {"enriched", !enriched.empty()}});
        }
        if (!enriched.empty()) fwd["47"] = enriched;
    }

    try {
        auto encoded = shared::iso_codec::encode(
            fwd, shared::iso_codec::encoding_from_config_string(cfg_.upstream.encoding));
        if (tracing) {
            trace_.hop(router_stan, "upstream_send", &encoded);
        }
        {
            std::lock_guard<std::mutex> lock(*entry.up_write_lock);
            shared::write_message(entry.up_fd, encoded, cfg_.upstream.framing);
        }
        stats_.record_sent();
        LOG_DEBUG("dispatcher: forwarded mti=" + mti + " to upstream, router_stan=" + router_stan +
                  " upstream_stan=" + entry.upstream_stan);
    } catch (const std::exception& e) {
        // Races session teardown closing the upstream socket from a different thread -- must
        // not propagate as an uncaught exception on the ds-receiver thread.
        LOG_ERROR(std::string("dispatcher: failed to write response to upstream: ") + e.what());
    }
    stats_.record_latency(
        "total", std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - entry.started_at).count());
    if (tracing) {
        trace_.finish(router_stan);
    }
}

void Dispatcher::reaper_loop() {
    while (!dispatcher_stop_.wait_for(std::chrono::seconds(1))) {
        std::vector<PendingEntry> expired;
        {
            std::lock_guard<std::mutex> lock(pending_mutex_);
            auto now = std::chrono::steady_clock::now();
            for (auto it = pending_.begin(); it != pending_.end();) {
                auto age_seconds = std::chrono::duration_cast<std::chrono::seconds>(now - it->second.created_at).count();
                if (age_seconds >= cfg_.pending_ttl_seconds) {
                    expired.push_back(it->second);
                    it = pending_.erase(it);
                } else {
                    ++it;
                }
            }
            if (!expired.empty()) {
                stats_.set_gauge("pending_count", static_cast<int>(pending_.size()));
            }
        }

        for (const auto& entry : expired) {
            try {
                std::map<std::string, std::string> decline = {{"t", "0110"}, {"11", entry.upstream_stan}, {"39", "91"}};
                auto encoded = shared::iso_codec::encode(
                    decline, shared::iso_codec::encoding_from_config_string(cfg_.upstream.encoding));
                {
                    std::lock_guard<std::mutex> lock(*entry.up_write_lock);
                    shared::write_message(entry.up_fd, encoded, cfg_.upstream.framing);
                }
                stats_.record_sent();
            } catch (const std::exception& e) {
                LOG_WARNING(std::string("dispatcher reaper: failed to send decline: ") + e.what());
            }
            LOG_WARNING("dispatcher reaper: pending entry for upstream_stan=" + entry.upstream_stan +
                        " expired, sent decline");
        }
    }
}

std::map<std::string, int> Dispatcher::purge() {
    int queue_dropped = 0;
    {
        std::lock_guard<std::mutex> lock(queue_mutex_);
        queue_dropped = static_cast<int>(queue_.size());
        queue_.clear();
        stats_.set_gauge("queue_depth", 0);
        queue_cv_not_full_.notify_all();
    }
    int response_queue_dropped = 0;
    {
        std::lock_guard<std::mutex> lock(response_queue_mutex_);
        response_queue_dropped = static_cast<int>(response_queue_.size());
        response_queue_.clear();
        stats_.set_gauge("response_queue_depth", 0);
        response_queue_cv_not_full_.notify_all();
    }
    int pending_dropped = 0;
    {
        std::lock_guard<std::mutex> lock(pending_mutex_);
        pending_dropped = static_cast<int>(pending_.size());
        pending_.clear();
        stats_.set_gauge("pending_count", 0);
    }
    return {{"queue_dropped", queue_dropped},
            {"response_queue_dropped", response_queue_dropped},
            {"pending_dropped", pending_dropped}};
}

std::vector<PendingSnapshotEntry> Dispatcher::pending_snapshot() {
    auto now = std::chrono::steady_clock::now();
    std::vector<PendingSnapshotEntry> entries;
    {
        std::lock_guard<std::mutex> lock(pending_mutex_);
        entries.reserve(pending_.size());
        for (const auto& [stan, entry] : pending_) {
            double age_seconds = std::chrono::duration<double>(now - entry.created_at).count();
            entries.push_back({stan, entry.upstream_stan, std::round(age_seconds * 1000.0) / 1000.0});
        }
    }
    std::sort(entries.begin(), entries.end(), [](const PendingSnapshotEntry& a, const PendingSnapshotEntry& b) {
        return a.age_seconds > b.age_seconds;
    });
    return entries;
}

void Dispatcher::drain_and_stop() {
    dispatcher_stop_.set();
    for (size_t i = 0; i < workers_.size(); ++i) {
        std::unique_lock<std::mutex> lock(queue_mutex_);
        queue_cv_not_full_.wait(lock, [this] { return queue_.size() < static_cast<size_t>(cfg_.queue_maxsize); });
        queue_.push_back(std::nullopt);
        queue_cv_not_empty_.notify_one();
    }
    for (size_t i = 0; i < response_workers_.size(); ++i) {
        std::unique_lock<std::mutex> lock(response_queue_mutex_);
        response_queue_cv_not_full_.wait(
            lock, [this] { return response_queue_.size() < static_cast<size_t>(cfg_.queue_maxsize); });
        response_queue_.push_back(std::nullopt);
        response_queue_cv_not_empty_.notify_one();
    }
    for (auto& t : workers_) {
        if (t.joinable()) t.join();
    }
    for (auto& t : response_workers_) {
        if (t.joinable()) t.join();
    }
    if (reaper_.joinable()) reaper_.join();

    // Session teardown (upstream or downstream disconnect, reconnect) previously discarded any
    // still-in-flight transactions with zero trace - unlike purge(), which reports
    // pending_dropped, this path left no log line explaining why a transaction just vanished.
    // There's nothing to *do* about them (the upstream client that would receive a decline is
    // already gone), but a live-diagnosis session needs the record. Safe without extra locking
    // beyond the move itself: every worker/response-worker thread that could still be mutating
    // pending_ has already been joined above.
    std::unordered_map<std::string, PendingEntry> dropped;
    {
        std::lock_guard<std::mutex> lock(pending_mutex_);
        dropped = std::move(pending_);
        pending_.clear();
    }
    for (const auto& [stan, entry] : dropped) {
        LOG_WARNING("dispatcher: session torn down with router_stan=" + stan + " still pending (upstream_stan=" +
                    entry.upstream_stan + "); abandoning");
    }
    if (!dropped.empty()) {
        LOG_WARNING("dispatcher: session teardown abandoned " + std::to_string(dropped.size()) +
                    " pending transaction(s)");
        stats_.set_gauge("pending_count", 0);
    }

    auto abandoned_traces = trace_.abandon_in_progress();
    if (!abandoned_traces.empty()) {
        LOG_WARNING("dispatcher: session teardown left " + std::to_string(abandoned_traces.size()) +
                    " in-progress trace(s) incomplete");
    }
}

}  // namespace router

#include "router/crypto_client.h"

#include <nlohmann/json.hpp>

#include "shared/base64.h"
#include "shared/log.h"

namespace router {

namespace {

// One worker thread's cached httplib::Client plus the bookkeeping that decides whether it's
// still usable - bundled into a single object instead of three loose thread_local variables kept
// in sync by hand, same idiom as this session's router_py/upstream_host refactor (_CachedConnection
// / _Connection: a cached resource that can go stale is modeled as one object with its own
// validity state, not scattered fields). httplib::Client isn't default-constructible without
// host/port, so this is heap-allocated (thread_local std::unique_ptr) rather than a bare
// thread_local struct.
struct CachedClient {
    httplib::Client client;
    int generation;
    std::chrono::steady_clock::time_point last_used;

    CachedClient(httplib::Client c, int gen)
        : client(std::move(c)), generation(gen), last_used(std::chrono::steady_clock::now()) {}
};

}  // namespace

CryptoClient::CryptoClient(const CryptoConfig& cfg, int breaker_threshold, int breaker_cooldown_seconds,
                           double idle_timeout_seconds)
    : cfg_(cfg),
      base_path_("/sys/v1/plugins/" + cfg.plugin_id),
      breaker_threshold_(breaker_threshold),
      breaker_cooldown_seconds_(breaker_cooldown_seconds),
      idle_timeout_seconds_(idle_timeout_seconds) {}

httplib::Client CryptoClient::make_client() const {
    if (cfg_.ssl_active) {
        std::string url = "https://" + cfg_.host + ":" + std::to_string(cfg_.port);
        // Same self-signed file doubles as this client's own identity (mutual TLS) when given -
        // matches router_py's crypto_client.py session.cert/verify split.
        httplib::Client client = (!cfg_.certfile.empty() && !cfg_.keyfile.empty())
                                      ? httplib::Client(url, cfg_.certfile, cfg_.keyfile)
                                      : httplib::Client(url);
        if (!cfg_.cafile.empty()) {
            client.set_ca_cert_path(cfg_.cafile);
            client.enable_server_certificate_verification(true);
        } else {
            client.enable_server_certificate_verification(false);
        }
        client.set_connection_timeout(5, 0);
        client.set_read_timeout(5, 0);
        client.set_write_timeout(5, 0);
        // httplib::Client defaults keep_alive_ to false, which closes (and for SSL, shuts down)
        // the socket after every single request regardless of this thread_local Client object
        // being reused across the thread's lifetime (see validate() below) - so without this,
        // every request pays a full mTLS handshake, not just the first one per thread. Matches
        // crypto_host_main.cpp's set_keep_alive_max_count(10000) on the server side, which only
        // helps if the client actually holds the connection open long enough to use it.
        client.set_keep_alive(true);
        client.set_tcp_nodelay(true);
        return client;
    }

    httplib::Client client(cfg_.host, cfg_.port);
    client.set_connection_timeout(5, 0);
    client.set_read_timeout(5, 0);
    client.set_write_timeout(5, 0);
    client.set_keep_alive(true);
    client.set_tcp_nodelay(true);
    return client;
}

void CryptoClient::record_failure() {
    std::lock_guard<std::mutex> lock(breaker_mutex_);
    ++failure_count_;
    if (failure_count_ >= breaker_threshold_) {
        open_until_ = std::chrono::steady_clock::now() + std::chrono::seconds(breaker_cooldown_seconds_);
        ++generation_;
    }
}

void CryptoClient::reset_failure() {
    std::lock_guard<std::mutex> lock(breaker_mutex_);
    failure_count_ = 0;
}

void CryptoClient::reset_breaker() {
    std::lock_guard<std::mutex> lock(breaker_mutex_);
    failure_count_ = 0;
    open_until_ = std::chrono::steady_clock::time_point{};
    ++generation_;
}

int CryptoClient::generation() {
    std::lock_guard<std::mutex> lock(breaker_mutex_);
    return generation_;
}

std::optional<std::string> CryptoClient::validate(const std::string& endpoint, const std::string& pan,
                                                   const std::string& f47, const std::string& router_stan) {
    {
        std::lock_guard<std::mutex> lock(breaker_mutex_);
        if (std::chrono::steady_clock::now() < open_until_) {
            return std::nullopt;
        }
    }

    nlohmann::json body = {{"operation", endpoint}, {"f2", pan}, {"f47", f47}, {"router_stan", router_stan}};
    httplib::Headers headers = {{"Authorization", "Bearer " + cfg_.bearer_token}};

    // One httplib::Client per calling thread (worker or response-worker), lazily built on
    // first use and reused for that thread's lifetime - httplib::Client isn't safe to share
    // across concurrent threads, and the dispatcher's worker pools call validate() from up to
    // worker_threads + response_worker_threads threads at once.
    //
    // Discarded and rebuilt proactively (not just on the next failed call) in two cases: (1) this
    // thread's cached client was built under a since-superseded generation - crypto_host died and
    // the breaker opened since, so the cached client is presumed stale even though this thread
    // itself hasn't seen a failure yet; (2) the cached client has been idle past
    // idle_timeout_seconds_ - crypto_host (cpp-httplib) closes its own keep-alive connections
    // after ~5s idle regardless of any breaker event, and a thread_local client sitting unused
    // across a traffic lull (e.g. a soak's tail-settle sleep between stress windows) has no way to
    // learn that from the client side short of trying it and failing. Same "anticipate staleness,
    // don't discover it by failing first" principle in both cases - mirrors router_py's
    // crypto_client.py _get_connection().
    thread_local std::unique_ptr<CachedClient> cached;
    int current_generation = generation();
    auto now = std::chrono::steady_clock::now();
    if (cached) {
        bool idle_too_long = (now - cached->last_used) > std::chrono::duration<double>(idle_timeout_seconds_);
        if (cached->generation != current_generation || idle_too_long) {
            cached.reset();
        }
    }
    if (!cached) {
        cached = std::make_unique<CachedClient>(make_client(), current_generation);
    } else {
        cached->last_used = now;
    }
    httplib::Client& client = cached->client;

    auto res = client.Post(base_path_, headers, body.dump(), "application/json");
    if (!res || res->status >= 400) {
        throttle_.log(shared::LogLevel::Warning, "crypto_call_failed:" + endpoint,
                       "crypto_client: " + endpoint + " request failed (router_stan=" + router_stan +
                           "), status=" + (res ? std::to_string(res->status) : std::string("(no response)")));
        record_failure();
        return std::nullopt;
    }

    try {
        // The 2XX body is a JSON string literal -- the PluginOutput envelope (base64,
        // "format": "byte"), not a JSON object wrapping it.
        std::string base64_str = nlohmann::json::parse(res->body).get<std::string>();
        auto decoded_bytes = shared::base64_decode(base64_str);
        std::string decoded_json(decoded_bytes.begin(), decoded_bytes.end());
        auto inner = nlohmann::json::parse(decoded_json);
        std::string f47_out = inner.value("f47", std::string(""));
        reset_failure();
        return f47_out;
    } catch (const std::exception& e) {
        throttle_.log(shared::LogLevel::Warning, "crypto_call_failed:" + endpoint,
                       "crypto_client: failed to decode PluginOutput envelope (router_stan=" + router_stan +
                           "): " + e.what());
        record_failure();
        return std::nullopt;
    }
}

}  // namespace router

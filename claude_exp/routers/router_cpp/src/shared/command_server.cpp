#include "shared/command_server.h"

#include <nlohmann/json.hpp>

#include "shared/log.h"

using json = nlohmann::json;
using namespace shared;

namespace {

void send_json(httplib::Response& res, int status, const json& obj) {
    res.set_header("Content-Type", "application/json");
    res.set_content(obj.dump(), "application/json");
    res.status = status;
}

std::string to_upper(const std::string& s) {
    std::string result = s;
    for (char& c : result) {
        c = std::toupper(static_cast<unsigned char>(c));
    }
    return result;
}

}  // namespace

CommandServer::CommandServer(int port, Stats& stats, StopEvent& stop_event,
                             const std::string& bind_host,
                             std::optional<std::string> auth_token)
    : port_(port),
      stats_(stats),
      stop_event_(stop_event),
      bind_host_(bind_host),
      auth_token_(auth_token),
      server_(std::make_unique<httplib::Server>()) {
    setup_builtin_routes();
}

CommandServer::~CommandServer() {
    stop();
    if (listen_thread_ && listen_thread_->joinable()) {
        listen_thread_->join();
    }
}

void CommandServer::setup_builtin_routes() {
    register_route("/stats", {"GET"}, /*protected=*/false, [this](const httplib::Request&, httplib::Response& res) {
        send_json(res, 200, stats_.snapshot());
    });

    register_route("/stop", {"GET", "POST"}, /*protected=*/true, [this](const httplib::Request&, httplib::Response& res) {
        stop_event_.set();
        send_json(res, 200, {{"status", "stopping"}});
    });

    register_route("/log_level", {"GET"}, /*protected=*/false, [](const httplib::Request&, httplib::Response& res) {
        auto level = Logger::instance().level();
        send_json(res, 200, {{"level", shared::to_string(level)}});
    });

    register_route("/log_level", {"POST"}, /*protected=*/true, [](const httplib::Request& req, httplib::Response& res) {
        try {
            auto body = json::parse(req.body);
            if (!body.contains("level")) {
                send_json(res, 400, {{"error", "missing 'level' field"}});
                return;
            }
            auto level_opt = shared::parse_log_level(body["level"].get<std::string>());
            if (!level_opt) {
                send_json(res, 400, {{"error", "invalid log level"}});
                return;
            }
            Logger::instance().set_level(level_opt.value());
            send_json(res, 200, {{"level", shared::to_string(level_opt.value())}});
        } catch (const std::exception& e) {
            send_json(res, 400, {{"error", std::string("parse error: ") + e.what()}});
        }
    });

    register_route("/logs", {"GET"}, /*protected=*/false, [](const httplib::Request& req, httplib::Response& res) {
        auto lines = Logger::instance().buffered_lines();
        auto format = req.get_param_value("format");

        if (format == "text") {
            // Each line is already a standalone JSON object (JSON-lines format) - fine to
            // ship/tail as-is without re-parsing.
            std::string text;
            for (const auto& line : lines) {
                text += line + "\n";
            }
            res.set_content(text, "text/plain");
            res.status = 200;
        } else {
            json parsed = json::array();
            for (const auto& line : lines) {
                try {
                    parsed.push_back(json::parse(line));
                } catch (const std::exception&) {
                    parsed.push_back(json{{"message", line}});
                }
            }
            send_json(res, 200, parsed);
        }
    });
}

void CommandServer::register_route(const std::string& path, const std::vector<std::string>& methods,
                                   bool protected_route, Handler handler) {
    auto wrapped = wrap_handler(protected_route, handler);

    for (const auto& method : methods) {
        auto method_upper = to_upper(method);
        if (method_upper == "GET") {
            server_->Get(path, wrapped);
        } else if (method_upper == "POST") {
            server_->Post(path, wrapped);
        }
    }
}

CommandServer::Handler CommandServer::wrap_handler(bool protected_route, Handler handler) {
    return [this, protected_route, handler](const httplib::Request& req, httplib::Response& res) {
        if (protected_route) {
            if (auth_token_) {
                auto auth_header = req.get_header_value("X-Router-Auth");
                if (auth_header != auth_token_.value()) {
                    send_json(res, 403, {{"error", "unauthorized"}});
                    return;
                }
            }
        }
        handler(req, res);
    };
}

void CommandServer::start() {
    listen_thread_ = std::make_unique<std::thread>([this] {
        server_->listen(bind_host_, port_);
    });
}

void CommandServer::stop() {
    if (server_) {
        server_->stop();
    }
}

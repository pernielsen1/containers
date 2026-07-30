import logging
import threading

from flask import Flask, jsonify, request

from shared.log_buffer import LogBuffer


class CommandServer:
    def __init__(self, port, stats, stop_event, bind_host: str = "127.0.0.1", auth_token=None):
        self.port = port
        self.stats = stats
        self.stop_event = stop_event
        self.bind_host = bind_host
        self.auth_token = auth_token

        self.app = Flask(__name__)
        logging.getLogger("werkzeug").setLevel(logging.ERROR)

        self.log_buffer = LogBuffer(maxlen=2000)
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        self.log_buffer.setFormatter(formatter)
        logging.getLogger().addHandler(self.log_buffer)

        self._register_builtin_routes()

    def _check_auth(self):
        if self.auth_token is None:
            return None
        token = request.headers.get("X-Router-Auth", "")
        if token != self.auth_token:
            return jsonify({"error": "unauthorized"}), 401
        return None

    def _register_builtin_routes(self):
        @self.app.route("/stats", methods=["GET"])
        def stats_route():
            return jsonify(self.stats.snapshot())

        @self.app.route("/stop", methods=["GET", "POST"])
        def stop_route():
            err = self._check_auth()
            if err:
                return err
            self.stop_event.set()
            return jsonify({"status": "stopping"})

        @self.app.route("/log_level", methods=["GET", "POST"])
        def log_level_route():
            if request.method == "POST":
                err = self._check_auth()
                if err:
                    return err
                level = (request.json or {}).get("level", "INFO").upper()
                logging.getLogger().setLevel(level)
                return jsonify({"level": level})
            return jsonify({"level": logging.getLevelName(logging.getLogger().level)})

        @self.app.route("/logs", methods=["GET"])
        def logs_route():
            lines = self.log_buffer.get_lines()
            fmt = request.args.get("format", "json")
            if fmt == "text":
                return "\n".join(lines), 200, {"Content-Type": "text/plain"}
            return jsonify(lines)

    def register(self, path, methods=("GET",), protected: bool = False):
        def decorator(fn):
            def wrapper(*args, **kwargs):
                if protected:
                    err = self._check_auth()
                    if err:
                        return err
                return fn(*args, **kwargs)

            wrapper.__name__ = fn.__name__
            self.app.add_url_rule(path, view_func=wrapper, methods=list(methods))
            return fn

        return decorator

    def start(self):
        thread = threading.Thread(
            target=lambda: self.app.run(host=self.bind_host, port=self.port, use_reloader=False),
            daemon=True,
        )
        thread.start()

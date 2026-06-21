import logging
import threading

from flask import Flask, Response, jsonify, request

from shared.log_buffer import LogBuffer

logging.getLogger("werkzeug").setLevel(logging.ERROR)


class CommandServer:
    """Flask HTTP command/stats API shared by all actors."""

    def __init__(self, port, stats, stop_event: threading.Event,
                 bind_host: str = "127.0.0.1", auth_token: str = None):
        self.port = port
        self.stats = stats
        self.stop_event = stop_event
        self.bind_host = bind_host
        self.auth_token = auth_token

        self.log_buffer = LogBuffer()
        self.log_buffer.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(self.log_buffer)

        self.app = Flask(__name__)
        self._register_builtin_routes()

    def _is_authorized(self) -> bool:
        # no-op check when auth_token is None — see Known limitations
        if self.auth_token is None:
            return True
        return request.headers.get("X-Router-Auth") == self.auth_token

    def _register_builtin_routes(self):
        app = self.app

        @app.route("/stats", methods=["GET"])
        def stats_route():
            return jsonify(self.stats.snapshot())

        @app.route("/stop", methods=["GET", "POST"])
        def stop_route():
            if not self._is_authorized():
                return jsonify({"error": "unauthorized"}), 403
            self.stop_event.set()
            return jsonify({"status": "stopping"})

        @app.route("/log_level", methods=["GET", "POST"])
        def log_level_route():
            if request.method == "POST":
                if not self._is_authorized():
                    return jsonify({"error": "unauthorized"}), 403
                body = request.get_json(silent=True) or {}
                level = body.get("level")
                if level:
                    logging.getLogger().setLevel(level.upper())
            current = logging.getLevelName(logging.getLogger().getEffectiveLevel())
            return jsonify({"level": current})

        @app.route("/logs", methods=["GET"])
        def logs_route():
            lines = self.log_buffer.get_lines()
            if request.args.get("format") == "text":
                return Response("\n".join(lines), mimetype="text/plain")
            return jsonify(lines)

    def register(self, path, methods=("GET",), protected: bool = False):
        """Add a custom route; protected=True requires header X-Router-Auth == auth_token
        (no-op check when auth_token is None — see Known limitations)."""

        def decorator(func):
            def wrapped(*args, **kwargs):
                if protected and not self._is_authorized():
                    return jsonify({"error": "unauthorized"}), 403
                return func(*args, **kwargs)

            wrapped.__name__ = f"{func.__name__}__{path.replace('/', '_')}"
            self.app.add_url_rule(path, endpoint=wrapped.__name__, view_func=wrapped, methods=list(methods))
            return func

        return decorator

    def start(self):
        thread = threading.Thread(
            target=lambda: self.app.run(
                host=self.bind_host, port=self.port, threaded=True, use_reloader=False
            ),
            daemon=True,
        )
        thread.start()

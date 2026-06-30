import logging
import threading

from flask import Flask, jsonify, request

from shared.log_buffer import LogBuffer

logger = logging.getLogger(__name__)


class CommandServer:
    def __init__(self, port, stats, stop_event, bind_host="127.0.0.1", auth_token=None):
        self._port = port
        self._stats = stats
        self._stop_event = stop_event
        self._bind_host = bind_host
        self._auth_token = auth_token

        self._app = Flask(__name__)
        logging.getLogger("werkzeug").setLevel(logging.ERROR)

        self._log_buffer = LogBuffer(maxlen=2000)
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        self._log_buffer.setFormatter(formatter)
        logging.getLogger().addHandler(self._log_buffer)

        self._register_builtins()

    def _check_auth(self):
        if self._auth_token is None:
            return None
        token = request.headers.get("X-Router-Auth", "")
        if token != self._auth_token:
            return jsonify({"error": "unauthorized"}), 401
        return None

    def _register_builtins(self):
        @self._app.route("/stats", methods=["GET"])
        def stats():
            return jsonify(self._stats.snapshot())

        @self._app.route("/stop", methods=["GET", "POST"])
        def stop():
            err = self._check_auth()
            if err:
                return err
            self._stop_event.set()
            return jsonify({"status": "stopping"})

        @self._app.route("/log_level", methods=["GET", "POST"])
        def log_level():
            if request.method == "POST":
                err = self._check_auth()
                if err:
                    return err
                level = request.json.get("level", "INFO").upper()
                logging.getLogger().setLevel(level)
                return jsonify({"level": level})
            return jsonify({"level": logging.getLevelName(logging.getLogger().level)})

        @self._app.route("/logs", methods=["GET"])
        def logs():
            lines = self._log_buffer.get_lines()
            fmt = request.args.get("format", "json")
            if fmt == "text":
                return "\n".join(lines), 200, {"Content-Type": "text/plain"}
            return jsonify(lines)

    def register(self, path, methods=("GET",), protected=False):
        def decorator(fn):
            def wrapper(*args, **kwargs):
                if protected:
                    err = self._check_auth()
                    if err:
                        return err
                return fn(*args, **kwargs)
            wrapper.__name__ = fn.__name__
            self._app.add_url_rule(path, view_func=wrapper, methods=list(methods))
            return fn
        return decorator

    def start(self):
        t = threading.Thread(
            target=lambda: self._app.run(host=self._bind_host, port=self._port, use_reloader=False),
            daemon=True,
        )
        t.start()

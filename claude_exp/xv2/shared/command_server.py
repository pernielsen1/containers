import logging
import threading
from flask import Flask, jsonify, request as flask_request, Response

from shared.log_buffer import LogBuffer

logging.getLogger("werkzeug").setLevel(logging.ERROR)

_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
_LOG_FORMAT = "%(asctime)s [%(threadName)s] %(levelname)s %(message)s"


class CommandServer:
    def __init__(self, port, stats, stop_event):
        self._port = port
        self._stats = stats
        self._stop_event = stop_event
        self._app = Flask(__name__)

        # install log buffer on root logger
        self._log_buffer = LogBuffer(maxlen=2000)
        self._log_buffer.setFormatter(logging.Formatter(_LOG_FORMAT))
        logging.getLogger().addHandler(self._log_buffer)

        self._app.add_url_rule("/stats",     "stats",     self._handle_stats,     methods=["GET"])
        self._app.add_url_rule("/stop",      "stop",      self._handle_stop,      methods=["GET", "POST"])
        self._app.add_url_rule("/log_level", "log_level", self._handle_log_level, methods=["GET", "POST"])
        self._app.add_url_rule("/logs",      "logs",      self._handle_logs,      methods=["GET"])

    def _handle_stats(self):
        return jsonify(self._stats.snapshot())

    def _handle_stop(self):
        self._stop_event.set()
        return jsonify({"status": "stopping"})

    def _handle_log_level(self):
        root = logging.getLogger()
        if flask_request.method == "POST":
            level = (flask_request.json or {}).get("level", "").upper()
            if level not in _LOG_LEVELS:
                return jsonify({"error": f"unknown level: {level}"}), 400
            root.setLevel(getattr(logging, level))
        return jsonify({"level": logging.getLevelName(root.level)})

    def _handle_logs(self):
        lines = self._log_buffer.get_lines()
        if flask_request.args.get("format") == "text":
            return Response("\n".join(lines), mimetype="text/plain")
        return jsonify(lines)

    def register(self, path, methods=("GET",)):
        def decorator(func):
            self._app.add_url_rule(path, func.__name__, func, methods=list(methods))
            return func
        return decorator

    def start(self):
        t = threading.Thread(
            target=self._app.run,
            kwargs={"host": "0.0.0.0", "port": self._port, "use_reloader": False},
            daemon=True,
        )
        t.start()

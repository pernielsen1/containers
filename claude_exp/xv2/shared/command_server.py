import logging
import threading
from flask import Flask, jsonify

logging.getLogger("werkzeug").setLevel(logging.ERROR)


class CommandServer:
    def __init__(self, port, stats, stop_event):
        self._port = port
        self._stats = stats
        self._stop_event = stop_event
        self._app = Flask(__name__)
        self._app.add_url_rule("/stats", "stats", self._handle_stats, methods=["GET"])
        self._app.add_url_rule("/stop", "stop", self._handle_stop, methods=["GET", "POST"])

    def _handle_stats(self):
        return jsonify(self._stats.snapshot())

    def _handle_stop(self):
        self._stop_event.set()
        return jsonify({"status": "stopping"})

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

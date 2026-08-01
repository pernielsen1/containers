import argparse
import base64
import json
import logging
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from flask import Flask, request  # noqa: E402

from shared.command_server import CommandServer  # noqa: E402
from shared.iso_utils import f47_decode, f47_encode  # noqa: E402
from shared.stats import Stats  # noqa: E402

logger = logging.getLogger(__name__)


def load_config(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    with open(path) as f:
        cfg = json.load(f)
    base_dir = os.path.dirname(os.path.abspath(path))
    cfg["pans_defined"] = os.path.normpath(os.path.join(base_dir, cfg["pans_defined"]))
    return cfg


class CryptoHostSim:
    """Stub crypto host: no OpenSSL, no PIN/ARQC/CVV2/AAV math - just reports whether the PAN
    is provisioned. Real cryptographic validation lives in routers/crypto_host/ (the shared
    container). Wire contract (Fortanix-shaped: POST /sys/v1/plugins/{plugin_id}, bearer auth,
    base64 PluginOutput response) matches that container and the Java/C++ stubs, so a router can
    point at either one via config alone."""

    def __init__(self, cfg):
        self.cfg = cfg
        with open(cfg["pans_defined"]) as f:
            self.pans = json.load(f)

        self.stats = Stats(yellow_threshold_seconds=cfg.get("yellow_threshold_seconds"))
        self.stop_event = threading.Event()

        # Command/stats API on command_port; the plugin-execution API below is a separate
        # listener on `port` (this is what router/crypto_client.py's CryptoConfig.port dials).
        self.cmd = CommandServer(cfg["command_port"], self.stats, self.stop_event)

        self.app = Flask(__name__)
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        self._register_routes()

    def _validate(self, pan: str, f47_str: str) -> str:
        data = f47_decode(f47_str)
        data["response_code"] = "14" if pan not in self.pans else "00"
        return f47_encode(data)

    def _register_routes(self) -> None:
        plugin_id = self.cfg["plugin_id"]
        bearer_token = self.cfg["bearer_token"]

        @self.app.route(f"/sys/v1/plugins/{plugin_id}", methods=["POST"])
        def invoke_plugin():
            auth_header = request.headers.get("Authorization")
            if auth_header != f"Bearer {bearer_token}":
                return {"error": "unauthorized"}, 401

            self.stats.record_recv()
            body = request.json or {}
            operation = body.get("operation", "")
            if operation not in ("validate_0100", "validate_0110"):
                return {"error": f"unknown operation: {operation}"}, 400

            result = self._validate(body.get("f2", ""), body.get("f47", ""))
            envelope = json.dumps({"f47": result})
            b64 = base64.b64encode(envelope.encode("utf-8")).decode("ascii")
            self.stats.record_sent()
            return json.dumps(b64), 200, {"Content-Type": "application/json"}

    def start(self) -> None:
        self.cmd.start()
        threading.Thread(
            target=lambda: self.app.run(host="127.0.0.1", port=self.cfg["port"], use_reloader=False),
            daemon=True,
        ).start()

    def run_forever(self) -> None:
        self.start()
        self.stop_event.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    args = parser.parse_args()

    cfg = load_config(args.config)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    sim = CryptoHostSim(cfg)
    sim.run_forever()

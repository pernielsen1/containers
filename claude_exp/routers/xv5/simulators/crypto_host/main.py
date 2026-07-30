import argparse
import base64
import json
import logging
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from flask import Flask, jsonify, request  # noqa: E402

from shared.command_server import CommandServer  # noqa: E402
from shared.crypto_utils import (  # noqa: E402
    calculate_arpc_method1,
    derive_session_key,
    derive_udk,
    verify_aav,
    verify_arqc,
    verify_cvv2,
    verify_pin,
)
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
    """Stateless HTTP service for cryptographic validation."""

    def __init__(self, cfg):
        self.cfg = cfg
        with open(cfg["pans_defined"]) as f:
            self.pans = json.load(f)

        self.stats = Stats(yellow_threshold_seconds=cfg.get("yellow_threshold_seconds"))
        self.stop_event = threading.Event()

        # Command/stats API on command_port; the REST validate API below is a separate
        # listener on `port` (this is what router/crypto_client.py's CryptoConfig.port dials).
        self.cmd = CommandServer(cfg["command_port"], self.stats, self.stop_event)

        self.app = Flask(__name__)
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        self._register_routes()

    def _validate(self, pan: str, f47_str: str) -> str:
        data = f47_decode(f47_str)

        if pan not in self.pans:
            data["response_code"] = "14"
            return f47_encode(data)

        pan_info = self.pans[pan]
        rc = "00"

        if "f52" in data:
            if not verify_pin(pan, data["f52"], pan_info["pek"], pan_info["pin"]):
                rc = "55"

        f55 = data.get("f55")
        message_type = data.get("message_type")

        if f55 and message_type == "0100" and rc == "00":
            if not verify_arqc(pan, pan_info["pan_seq"], pan_info["imk_ac"], f55):
                rc = "82"

        if f55 and message_type == "0110":
            udk = derive_udk(pan_info["imk_ac"], pan, pan_info["pan_seq"])
            sk = derive_session_key(udk, f55.get("atc", "0000"))
            arc_hex = rc.encode("ascii").hex()
            arpc = calculate_arpc_method1(f55.get("cryptogram", "0" * 16), arc_hex, sk)
            f55["arpc"] = base64.b64encode(arpc).decode("ascii")

        if "cvv2" in data and rc == "00":
            if not verify_cvv2(pan, data.get("f14", ""), data["cvv2"], pan_info["cvk"]):
                rc = "N7"

        if "aav" in data and rc == "00":
            if not verify_aav(data, pan_info["aav_key"], pan):
                rc = "82"

        data["response_code"] = rc
        return f47_encode(data)

    def _register_routes(self) -> None:
        @self.app.route("/validate_0100", methods=["POST"])
        def validate_0100():
            self.stats.record_recv()
            body = request.json or {}
            result = self._validate(body.get("f2", ""), body.get("f47", ""))
            self.stats.record_sent()
            return jsonify({"f47": result})

        @self.app.route("/validate_0110", methods=["POST"])
        def validate_0110():
            self.stats.record_recv()
            body = request.json or {}
            result = self._validate(body.get("f2", ""), body.get("f47", ""))
            self.stats.record_sent()
            return jsonify({"f47": result})

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

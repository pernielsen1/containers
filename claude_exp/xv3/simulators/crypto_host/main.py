import argparse
import base64
import json
import logging
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from flask import Flask, jsonify, request

from shared.command_server import CommandServer
from shared.crypto_utils import (
    calculate_arpc_method1,
    derive_session_key,
    derive_udk,
    verify_aav,
    verify_arqc,
    verify_cvv2,
    verify_pin,
)
from shared.iso_utils import f47_decode, f47_encode
from shared.stats import Stats

logger = logging.getLogger(__name__)


def load_config(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    with open(path) as f:
        cfg = json.load(f)
    base_dir = os.path.dirname(os.path.abspath(path))
    cfg["pans_defined"] = os.path.normpath(os.path.join(base_dir, cfg["pans_defined"]))
    if "iso_spec" in cfg:
        cfg["iso_spec"] = os.path.normpath(os.path.join(base_dir, cfg["iso_spec"]))
    return cfg


class CryptoHostSim:
    """Stateless HTTP service for cryptographic validation."""

    def __init__(self, cfg):
        self.cfg = cfg
        with open(cfg["pans_defined"]) as f:
            self.pans = json.load(f)

        self.stats = Stats(yellow_threshold_seconds=cfg.get("yellow_threshold_seconds"))
        self.stop_event = threading.Event()
        self.cmd = CommandServer(cfg["command_port"], self.stats, self.stop_event)

        self.api_app = Flask("crypto_host_api")
        self._register_api_routes()

    def _validate(self, pan: str, f47_str: str) -> str:
        data = f47_decode(f47_str)

        if pan not in self.pans:
            data["response_code"] = "14"
            return f47_encode(data)

        keys = self.pans[pan]
        response_code = data.get("response_code", "00")
        message_type = data.get("message_type")
        f55 = data.get("f55")

        # A malformed/incomplete crypto sub-block (bad hex, missing field) must decline,
        # not crash the request — crypto_host is a validation boundary and the dispatcher
        # always calls it regardless of what's actually present in f47.
        if data.get("f52"):
            try:
                if not verify_pin(pan, data["f52"], keys["pek"], keys["pin"]):
                    response_code = "55"
            except (KeyError, ValueError, TypeError):
                response_code = "55"

        if f55 and message_type == "0100" and response_code == "00":
            try:
                if not verify_arqc(pan, keys["pan_seq"], keys["imk_ac"], f55):
                    response_code = "82"
            except (KeyError, ValueError, TypeError):
                response_code = "82"

        if f55 and message_type == "0110":
            try:
                udk = derive_udk(keys["imk_ac"], pan, keys["pan_seq"])
                sk = derive_session_key(udk, f55["atc"])
                arc_hex = response_code.encode("ascii").hex()
                arpc = calculate_arpc_method1(f55["cryptogram"], arc_hex, sk)
                f55["arpc"] = base64.b64encode(arpc).decode()
                data["f55"] = f55
            except (KeyError, ValueError, TypeError):
                pass

        if data.get("cvv2") and response_code == "00":
            try:
                if not verify_cvv2(pan, data.get("f14", ""), data["cvv2"], keys["cvk"]):
                    response_code = "N7"
            except (KeyError, ValueError, TypeError):
                response_code = "N7"

        if data.get("aav") and response_code == "00":
            try:
                if not verify_aav(data, keys["aav_key"], pan):
                    response_code = "82"
            except (KeyError, ValueError, TypeError):
                response_code = "82"

        data["response_code"] = response_code
        return f47_encode(data)

    def _register_api_routes(self):
        @self.api_app.route("/validate_0100", methods=["POST"])
        def validate_0100():
            body = request.get_json()
            self.stats.record_recv()
            result = self._validate(body["f2"], body.get("f47", ""))
            self.stats.record_sent()
            return jsonify({"f47": result})

        @self.api_app.route("/validate_0110", methods=["POST"])
        def validate_0110():
            body = request.get_json()
            self.stats.record_recv()
            result = self._validate(body["f2"], body.get("f47", ""))
            self.stats.record_sent()
            return jsonify({"f47": result})

    def start(self):
        self.cmd.start()
        threading.Thread(
            target=lambda: self.api_app.run(
                host="0.0.0.0", port=self.cfg["port"], threaded=True, use_reloader=False
            ),
            daemon=True,
        ).start()

    def run_forever(self):
        self.start()
        self.stop_event.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    args = parser.parse_args()

    cfg = load_config(args.config)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    sim = CryptoHostSim(cfg)
    sim.run_forever()


if __name__ == "__main__":
    main()

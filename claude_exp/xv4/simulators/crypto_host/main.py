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
    verify_arqc,
    verify_aav,
    verify_cvv2,
    verify_pin,
)
from shared.iso_utils import f47_decode, f47_encode
from shared.stats import Stats

logger = logging.getLogger(__name__)


class CryptoHost:
    def __init__(self, cfg, pans):
        self._cfg = cfg
        self._pans = pans
        self.stats = Stats(yellow_threshold_seconds=cfg.get("yellow_threshold_seconds"))
        self.stop_event = threading.Event()

    def _validate(self, pan: str, f47_str: str) -> str:
        data = f47_decode(f47_str)
        response_code = "00"

        if pan not in self._pans:
            data["response_code"] = "14"
            return f47_encode(data)

        pan_data = self._pans[pan]

        if "f52" in data and response_code == "00":
            ok = verify_pin(pan, data["f52"], pan_data["pek"], pan_data["pin"])
            if not ok:
                response_code = "55"

        if "f55" in data and data.get("message_type") == "0100" and response_code == "00":
            ok = verify_arqc(pan, pan_data["pan_seq"], pan_data["imk_ac"], data["f55"])
            if not ok:
                response_code = "82"

        if "f55" in data and data.get("message_type") == "0110":
            try:
                udk_hex = derive_udk(pan_data["imk_ac"], pan, pan_data["pan_seq"])
                sk_hex = derive_session_key(udk_hex, data["f55"]["atc"])
                arqc_hex = data["f55"]["cryptogram"]
                arc_hex = "3030"  # Approval RC in ASCII hex
                arpc = calculate_arpc_method1(arqc_hex, arc_hex, sk_hex)
                import base64
                data["f55"]["arpc"] = base64.b64encode(arpc).decode()
            except Exception as e:
                logger.warning("ARPC computation failed: %s", e)

        if "cvv2" in data and response_code == "00":
            ok = verify_cvv2(pan, data.get("f14", ""), data["cvv2"], pan_data["cvk"])
            if not ok:
                response_code = "N7"

        if "aav" in data and response_code == "00":
            ok = verify_aav(data, pan_data["aav_key"], pan)
            if not ok:
                response_code = "82"

        data["response_code"] = response_code
        return f47_encode(data)

    def run(self, port):
        app = Flask(__name__)
        logging.getLogger("werkzeug").setLevel(logging.ERROR)

        @app.route("/validate_0100", methods=["POST"])
        def validate_0100():
            body = request.json
            pan = body.get("f2", "")
            f47_str = body.get("f47", "")
            # Set message_type for ARQC check
            data = f47_decode(f47_str)
            data["message_type"] = "0100"
            f47_str = f47_encode(data)
            result = self._validate(pan, f47_str)
            self.stats.record_recv()
            self.stats.record_sent()
            return jsonify({"f47": result})

        @app.route("/validate_0110", methods=["POST"])
        def validate_0110():
            body = request.json
            pan = body.get("f2", "")
            f47_str = body.get("f47", "")
            data = f47_decode(f47_str)
            data["message_type"] = "0110"
            f47_str = f47_encode(data)
            result = self._validate(pan, f47_str)
            self.stats.record_recv()
            self.stats.record_sent()
            return jsonify({"f47": result})

        app.run(host="0.0.0.0", port=port, use_reloader=False)


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    cfg_path = os.path.join(base, "config.json")
    with open(cfg_path) as f:
        cfg = json.load(f)

    pans_path = os.path.normpath(os.path.join(base, cfg["pans_defined"]))
    with open(pans_path) as f:
        pans = json.load(f)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    host = CryptoHost(cfg, pans)

    cmd = CommandServer(
        port=cfg["command_port"],
        stats=host.stats,
        stop_event=host.stop_event,
    )
    cmd.start()

    host.run(cfg["port"])


if __name__ == "__main__":
    main()

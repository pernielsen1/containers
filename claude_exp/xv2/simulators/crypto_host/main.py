#!/usr/bin/env python3
import json
import logging
import os
import threading
from flask import Flask, jsonify, request

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from shared.stats import Stats
from shared.command_server import CommandServer
from shared.iso_utils import f47_decode, f47_encode
from shared.crypto_utils import (
    derive_udk,
    derive_session_key,
    verify_arqc,
    calculate_arpc_method1,
    verify_pin,
    verify_cvv2,
    verify_aav,
)
import base64

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)


def load_config():
    base = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(base, "config.json")) as f:
        return json.load(f)


def load_pans(cfg):
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, cfg["pans_defined"])
    with open(path) as f:
        return json.load(f)


def _validate(pan, f47_str, pans):
    data = f47_decode(f47_str)
    pan_data = pans.get(pan)
    response_code = "00"

    if pan_data is None:
        data["response_code"] = "14"  # invalid card number
        return f47_encode(data)

    msg_type = data.get("message_type", "")

    # PIN verification
    if "f52" in data and data["f52"]:
        ok = verify_pin(pan, data["f52"], pan_data["pek"], pan_data["pin"])
        log.debug("PIN verify pan=%s ok=%s", pan, ok)
        if not ok:
            response_code = "55"

    # ARQC verification (authorization request)
    if "f55" in data and data["f55"] and msg_type == "0100" and response_code == "00":
        f55 = data["f55"]
        ok = verify_arqc(pan, pan_data["pan_seq"], pan_data["imk_ac"], f55)
        log.debug("ARQC verify pan=%s ok=%s", pan, ok)
        if not ok:
            response_code = "82"

    # ARPC calculation (authorization response)
    if "f55" in data and data["f55"] and msg_type == "0110":
        f55 = data["f55"]
        atc = f55.get("atc", "0001")
        udk = derive_udk(pan_data["imk_ac"], pan, pan_data["pan_seq"])
        sk  = derive_session_key(udk, atc)
        arqc_hex = f55.get("cryptogram", "0000000000000000")
        # ARC is the 2-byte authorization response code (ASCII hex of response_code)
        arc_hex = response_code.encode("ascii").hex()
        arpc = calculate_arpc_method1(arqc_hex, arc_hex, sk)
        data["f55"]["arpc"] = base64.b64encode(arpc).decode()
        log.debug("ARPC calculated pan=%s arpc=%s", pan, data["f55"]["arpc"])

    # CVV2 verification
    if "cvv2" in data and data["cvv2"] and response_code == "00":
        ok = verify_cvv2(pan, data.get("f14", ""), data["cvv2"], pan_data["cvk"])
        log.debug("CVV2 verify pan=%s ok=%s", pan, ok)
        if not ok:
            response_code = "N7"

    # AAV verification
    if "aav" in data and data["aav"] and response_code == "00":
        ok = verify_aav(data, pan_data["aav_key"], pan)
        log.debug("AAV verify pan=%s ok=%s", pan, ok)
        if not ok:
            response_code = "82"

    data["response_code"] = response_code
    return f47_encode(data)


def run(cfg=None, stop_event=None, stats=None):
    if cfg is None:
        cfg = load_config()
    if stop_event is None:
        stop_event = threading.Event()
    if stats is None:
        stats = Stats(yellow_threshold_seconds=cfg.get("yellow_threshold_seconds"))

    logging.getLogger().setLevel(
        getattr(logging, cfg.get("log_level", "INFO").upper(), logging.INFO)
    )

    pans = load_pans(cfg)
    app = Flask(__name__)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    @app.route("/validate_0100", methods=["POST"])
    def validate_0100():
        body = request.get_json(force=True)
        pan = body.get("f2", "")
        f47 = body.get("f47", "")
        stats.record_recv()
        result = _validate(pan, f47, pans)
        stats.record_sent()
        log.debug("validate_0100 pan=%s result=%s", pan, result)
        return jsonify({"f47": result})

    @app.route("/validate_0110", methods=["POST"])
    def validate_0110():
        body = request.get_json(force=True)
        pan = body.get("f2", "")
        f47 = body.get("f47", "")
        stats.record_recv()
        result = _validate(pan, f47, pans)
        stats.record_sent()
        log.debug("validate_0110 pan=%s result=%s", pan, result)
        return jsonify({"f47": result})

    cmd = CommandServer(cfg["command_port"], stats, stop_event)
    cmd.start()

    log.info("crypto_host REST on :%d  command on :%d", cfg["port"], cfg["command_port"])

    app.run(host="0.0.0.0", port=cfg["port"], use_reloader=False)


if __name__ == "__main__":
    run()

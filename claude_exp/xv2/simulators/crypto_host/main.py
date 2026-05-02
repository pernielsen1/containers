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
    if pan in pans:
        data["crypto_result"] = pans[pan]["crypto_result"]
    else:
        data["crypto_result"] = False
    return f47_encode(data)


def run(cfg=None, stop_event=None, stats=None):
    if cfg is None:
        cfg = load_config()
    if stop_event is None:
        stop_event = threading.Event()
    if stats is None:
        stats = Stats()

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

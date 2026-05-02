#!/usr/bin/env python3
import csv
import io
import json
import logging
import os
import socket
import threading
import time

import iso8583
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from flask import Flask, jsonify, request as flask_request

from shared.framing import read_message, write_message
from shared.stats import Stats
from shared.command_server import CommandServer
from shared.iso_utils import load_spec

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


def run(cfg=None, stop_event=None, stats=None):
    if cfg is None:
        cfg = load_config()
    if stop_event is None:
        stop_event = threading.Event()
    if stats is None:
        stats = Stats()

    base = os.path.dirname(os.path.abspath(__file__))
    spec = load_spec(os.path.join(base, cfg["iso_spec"]))
    framing = cfg["framing"]
    binary_fields = frozenset(k for k, v in spec.items() if v.get("data_enc") == "b")
    auto_fields = frozenset({"h", "p", "1"}) | binary_fields

    state = {
        "csv_path": None,
        "results": [],
        "results_lock": threading.Lock(),
        "conn": None,
        "conn_lock": threading.Lock(),
        "pending": {},
        "pending_lock": threading.Lock(),
        "stan_seq": 0,
        "stan_lock": threading.Lock(),
    }

    def next_stan():
        with state["stan_lock"]:
            state["stan_seq"] += 1
            return str(state["stan_seq"]).zfill(6)

    def connect():
        rcfg = cfg["router"]
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((rcfg["host"], rcfg["port"]))
        with state["conn_lock"]:
            state["conn"] = s
        log.info("upstream_host: connected to router %s:%d", rcfg["host"], rcfg["port"])
        return s

    def receive_loop(conn):
        while not stop_event.is_set():
            try:
                data = read_message(conn, framing)
            except ConnectionError:
                log.info("upstream_host: router disconnected")
                return
            stats.record_recv()
            try:
                resp, _ = iso8583.decode(data, spec=spec)
            except Exception as e:
                log.warning("upstream_host decode error: %s", e)
                continue
            stan = resp.get("11", "")
            with state["pending_lock"]:
                req_row = state["pending"].pop(stan, {})
            row = dict(req_row)
            for k, v in resp.items():
                row[f"resp_{k}"] = v
            with state["results_lock"]:
                state["results"].append(row)
            log.debug("upstream_host: response STAN=%s rc=%s", stan, resp.get("39", ""))

    def send_loop(conn, rows):
        valid_cols = [c for c in rows[0].keys() if c in spec and c not in auto_fields]
        for row in rows:
            if stop_event.is_set():
                break
            stan = next_stan()
            doc = {}
            for col in valid_cols:
                val = str(row.get(col, "")).strip()
                if val:
                    fspec = spec[col]
                    if fspec.get("len_type", -1) == 0 and fspec.get("data_enc") != "b":
                        val = val.zfill(fspec["max_len"])
                    doc[col] = val
            doc["t"] = "0100"
            doc["11"] = stan
            with state["pending_lock"]:
                state["pending"][stan] = dict(row)
            try:
                encoded, _ = iso8583.encode(doc, spec=spec)
                write_message(conn, encoded, framing)
                stats.record_sent()
                log.debug("upstream_host: sent STAN=%s", stan)
            except Exception as e:
                log.warning("upstream_host send error STAN=%s: %s", stan, e)
                with state["pending_lock"]:
                    state["pending"].pop(stan, None)
            time.sleep(0.02)

    # ── command server ─────────────────────────────────────────────────────────
    cmd = CommandServer(cfg["command_port"], stats, stop_event)

    @cmd.register("/upload", methods=("POST",))
    def upload():
        f = flask_request.files.get("file")
        if f is None:
            return jsonify({"error": "no file"}), 400
        dest = os.path.join(base, cfg.get("input_dir", "input"), "test_cases.csv")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        f.save(dest)
        state["csv_path"] = dest
        log.info("upstream_host: uploaded CSV → %s", dest)
        return jsonify({"status": "uploaded", "path": dest})

    @cmd.register("/start")
    def start():
        csv_path = state["csv_path"]
        if not csv_path or not os.path.exists(csv_path):
            return jsonify({"error": "no CSV uploaded"}), 400
        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            rows = list(reader)
        if not rows:
            return jsonify({"error": "CSV is empty"}), 400
        try:
            conn = connect()
        except OSError as e:
            return jsonify({"error": str(e)}), 503
        threading.Thread(target=receive_loop, args=(conn,), daemon=True).start()
        threading.Thread(target=send_loop, args=(conn, rows), daemon=True).start()
        return jsonify({"status": "started", "rows": len(rows)})

    @cmd.register("/results")
    def results():
        with state["results_lock"]:
            return jsonify(state["results"])

    cmd.start()
    log.info("upstream_host command server on :%d", cfg["command_port"])

    stop_event.wait()
    with state["conn_lock"]:
        if state["conn"]:
            state["conn"].close()
    log.info("upstream_host stopped")


if __name__ == "__main__":
    run()

#!/usr/bin/env python3
import argparse
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
from shared.iso_utils import load_spec, hex_dump, build_0800

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)


def load_config(path=None):
    if path is None:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "..", "upstream_1", "config.json")
    config_base = os.path.dirname(os.path.abspath(path))
    with open(path) as f:
        return json.load(f), config_base


def run(cfg=None, stop_event=None, stats=None, _config_base=None):
    if cfg is None:
        cfg, _config_base = load_config()
    if _config_base is None:
        _config_base = os.path.dirname(os.path.abspath(__file__))
    if stop_event is None:
        stop_event = threading.Event()
    if stats is None:
        stats = Stats(yellow_threshold_seconds=cfg.get("yellow_threshold_seconds"))

    logging.getLogger().setLevel(
        getattr(logging, cfg.get("log_level", "INFO").upper(), logging.INFO)
    )

    spec = load_spec(os.path.join(_config_base, cfg["iso_spec"]))
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

    mode = cfg.get("mode", "client")
    reestablish_seconds = cfg.get("reestablish_seconds", 10)

    def connect():
        rcfg = cfg["router"]
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((rcfg["host"], rcfg["port"]))
        with state["conn_lock"]:
            state["conn"] = s
        log.info("upstream_host: connected to router %s:%d", rcfg["host"], rcfg["port"])
        return s

    ping_interval = cfg.get("ping_0800_seconds", 30)

    def _keepalive_sender(conn, stop_evt, disc_evt):
        while not stop_evt.is_set() and not disc_evt.is_set():
            disc_evt.wait(timeout=ping_interval)
            if stop_evt.is_set() or disc_evt.is_set():
                break
            try:
                write_message(conn, build_0800(spec), framing)
                log.debug("upstream_host: sent 0800 keepalive")
            except Exception:
                disc_evt.set()
                break

    def receive_loop(conn, disc_evt):
        while not stop_event.is_set() and not disc_evt.is_set():
            try:
                data = read_message(conn, framing)
            except ConnectionError:
                log.info("upstream_host: router disconnected")
                disc_evt.set()
                return
            stats.record_recv()
            hex_dump("RECV router", data, log)
            try:
                resp, _ = iso8583.decode(data, spec=spec)
            except Exception as e:
                log.warning("upstream_host decode error: %s", e)
                continue
            mti = resp.get("t")
            if mti == "0810":
                log.debug("upstream_host: received 0810 keepalive response F24=%s",
                          resp.get("24"))
                continue
            if mti != "0110":
                log.warning("upstream_host: unexpected MTI %s", mti)
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
        dest = os.path.join(_config_base, cfg.get("input_dir", "input"), "test_cases.csv")
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
        if mode == "server":
            with state["conn_lock"]:
                conn = state["conn"]
            if conn is None:
                return jsonify({"error": "router not connected yet"}), 503
        else:
            with state["conn_lock"]:
                conn = state["conn"]
            if conn is None:
                return jsonify({"error": "router not connected yet"}), 503
        threading.Thread(target=send_loop, args=(conn, rows), daemon=True).start()
        return jsonify({"status": "started", "rows": len(rows)})

    @cmd.register("/results")
    def results():
        with state["results_lock"]:
            return jsonify(state["results"])

    cmd.start()
    log.info("upstream_host command server on :%d", cfg["command_port"])

    if mode == "server":
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("", cfg["port"]))
        srv.listen(5)
        log.info("upstream_host: server mode, listening on :%d", cfg["port"])

        def _accept_loop():
            while not stop_event.is_set():
                srv.settimeout(1)
                try:
                    conn, addr = srv.accept()
                except socket.timeout:
                    continue
                except OSError:
                    return
                log.info("upstream_host: router connected from %s", addr)
                disc_evt = threading.Event()
                with state["conn_lock"]:
                    old = state["conn"]
                    if old:
                        try:
                            old.close()
                        except OSError:
                            pass
                    state["conn"] = conn
                with state["results_lock"]:
                    state["results"] = []
                threading.Thread(target=receive_loop, args=(conn, disc_evt),
                                 daemon=True).start()
                threading.Thread(target=_keepalive_sender, args=(conn, stop_event, disc_evt),
                                 daemon=True).start()

        threading.Thread(target=_accept_loop, daemon=True, name="srv-acceptor").start()
        stop_event.wait()

    else:
        # client mode: connect and reconnect on disconnect
        rcfg = cfg["router"]
        while not stop_event.is_set():
            try:
                conn = connect()
            except OSError as e:
                log.info("upstream_host: router %s:%d unavailable (%s), retrying in %ds",
                         rcfg["host"], rcfg["port"], e, reestablish_seconds)
                stop_event.wait(timeout=reestablish_seconds)
                continue

            disc_evt = threading.Event()
            threading.Thread(target=receive_loop, args=(conn, disc_evt),
                             daemon=True).start()
            threading.Thread(target=_keepalive_sender, args=(conn, stop_event, disc_evt),
                             daemon=True).start()

            # wait until disconnected or stopped
            while not disc_evt.is_set() and not stop_event.is_set():
                stop_event.wait(timeout=1)

            with state["conn_lock"]:
                state["conn"] = None
            try:
                conn.close()
            except OSError:
                pass

            if stop_event.is_set():
                break
            log.info("upstream_host: disconnected, reconnecting in %ds", reestablish_seconds)
            stop_event.wait(timeout=reestablish_seconds)

    with state["conn_lock"]:
        if state["conn"]:
            state["conn"].close()
    log.info("upstream_host stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None, help="Path to config.json")
    args = parser.parse_args()
    cfg, config_base = load_config(args.config)
    run(cfg=cfg, _config_base=config_base)

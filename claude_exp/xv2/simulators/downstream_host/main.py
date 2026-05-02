#!/usr/bin/env python3
import json
import logging
import os
import queue
import socket
import threading

import iso8583
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from shared.framing import read_message, write_message
from shared.stats import Stats
from shared.command_server import CommandServer
from shared.iso_utils import load_spec, f47_decode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

_auth_counter = 0
_auth_lock = threading.Lock()


def _next_auth_code():
    global _auth_counter
    with _auth_lock:
        _auth_counter += 1
        return str(_auth_counter).zfill(6)


def _process_0100(req, pans):
    pan = req.get("2", "")
    resp = {"t": "0110"}
    for fld in ("2", "3", "4", "11", "37", "41", "42"):
        if fld in req:
            resp[fld] = req[fld]

    if pan not in pans:
        resp["39"] = "01"
        log.debug("Declined unknown PAN=%s", pan)
        return resp

    f47_data = f47_decode(req.get("47", ""))
    if not f47_data.get("crypto_result", False):
        resp["39"] = "01"
        log.debug("Declined crypto_result=False PAN=%s", pan)
        return resp

    resp["39"] = "00"
    resp["38"] = _next_auth_code()
    if "47" in req:
        resp["47"] = req["47"]
    log.debug("Approved PAN=%s auth=%s", pan, resp["38"])
    return resp


def _handle_client(conn, addr, framing, spec, pans, stats):
    send_q = queue.Queue()
    stop_ev = threading.Event()

    def receiver():
        while not stop_ev.is_set():
            try:
                data = read_message(conn, framing)
            except ConnectionError:
                log.info("downstream_host: client %s disconnected", addr)
                stop_ev.set()
                send_q.put(None)
                return
            stats.record_recv()
            try:
                req, _ = iso8583.decode(data, spec=spec)
            except Exception as e:
                log.warning("Decode error from %s: %s", addr, e)
                continue
            if req.get("t") != "0100":
                log.warning("Unexpected MTI %s from %s", req.get("t"), addr)
                continue
            resp = _process_0100(req, pans)
            send_q.put(resp)

    def sender():
        while True:
            item = send_q.get()
            if item is None:
                return
            try:
                encoded, _ = iso8583.encode(item, spec=spec)
                write_message(conn, encoded, framing)
                stats.record_sent()
            except Exception as e:
                log.warning("Send error to %s: %s", addr, e)

    rt = threading.Thread(target=receiver, name=f"ds-recv-{addr}", daemon=True)
    st = threading.Thread(target=sender, name=f"ds-send-{addr}", daemon=True)
    rt.start()
    st.start()
    stop_ev.wait()
    conn.close()
    rt.join(timeout=3)
    st.join(timeout=3)


def load_config():
    base = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(base, "config.json")) as f:
        return json.load(f)


def load_pans(cfg):
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, cfg["pans_defined"])
    with open(path) as f:
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
    pans = load_pans(cfg)
    framing = cfg["framing"]

    cmd = CommandServer(cfg["command_port"], stats, stop_event)
    cmd.start()

    srv_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv_sock.bind(("", cfg["port"]))
    srv_sock.listen(5)
    log.info("downstream_host listening on :%d  command on :%d", cfg["port"], cfg["command_port"])

    try:
        while not stop_event.is_set():
            srv_sock.settimeout(1)
            try:
                conn, addr = srv_sock.accept()
            except socket.timeout:
                continue
            log.info("downstream_host: accepted %s", addr)
            t = threading.Thread(
                target=_handle_client,
                args=(conn, addr, framing, spec, pans, stats),
                daemon=True,
            )
            t.start()
    finally:
        srv_sock.close()
        log.info("downstream_host stopped")


if __name__ == "__main__":
    run()

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

from shared.stats import Stats
from shared.command_server import CommandServer
from shared.iso_utils import load_spec, f47_decode, hex_dump
from shared import ims_connect

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


def _handle_from_conn(conn, addr, from_connections, from_lock, stats):
    """Read resume TPIPE, register send queue, then stream responses back to router."""
    try:
        irm_f0, client_id, _ = ims_connect.read_request(conn)
    except ConnectionError as e:
        log.warning("downstream_host: from_conn %s handshake failed: %s", addr, e)
        conn.close()
        return

    if irm_f0 != 0x80:
        log.warning("downstream_host: expected resume TPIPE from %s, got IRM_F0=0x%02x", addr, irm_f0)
        conn.close()
        return

    send_q = queue.Queue()
    with from_lock:
        from_connections[client_id] = send_q
    log.info("downstream_host: from_conn registered client=%s addr=%s",
             client_id.decode("cp500", errors="replace").rstrip(), addr)

    try:
        while True:
            item = send_q.get()
            if item is None:
                return
            ims_connect.write_response(conn, item)
            stats.record_sent()
    except OSError as e:
        log.warning("downstream_host: from_conn send error %s: %s", addr, e)
    finally:
        with from_lock:
            from_connections.pop(client_id, None)
        conn.close()


def _handle_to_conn(conn, addr, spec, pans, from_connections, from_lock, stats):
    """Read IMS-framed 0100 messages, process, route encoded 0110 to the matching from_conn."""
    try:
        while True:
            try:
                irm_f0, client_id, iso_data = ims_connect.read_request(conn)
            except ConnectionError:
                log.info("downstream_host: to_conn %s disconnected", addr)
                return

            if not iso_data:
                continue

            stats.record_recv()
            hex_dump(f"RECV {addr}", iso_data, log)

            try:
                req, _ = iso8583.decode(iso_data, spec=spec)
            except Exception as e:
                log.warning("Decode error from %s: %s", addr, e)
                continue

            if req.get("t") != "0100":
                log.warning("Unexpected MTI %s from %s", req.get("t"), addr)
                continue

            resp = _process_0100(req, pans)

            try:
                encoded, _ = iso8583.encode(resp, spec=spec)
            except Exception as e:
                log.warning("Encode error: %s", e)
                continue

            with from_lock:
                send_q = from_connections.get(client_id)

            if send_q is None:
                log.warning("downstream_host: no from_conn for client_id=%s",
                            client_id.decode("cp500", errors="replace").rstrip())
                continue

            send_q.put(encoded)
    finally:
        conn.close()


def _accept_loop(srv_sock, stop_event, handler, *args):
    while not stop_event.is_set():
        srv_sock.settimeout(1)
        try:
            conn, addr = srv_sock.accept()
        except socket.timeout:
            continue
        except OSError:
            return
        log.info("downstream_host: accepted %s on %s", addr, srv_sock.getsockname())
        threading.Thread(target=handler, args=(conn, addr) + args, daemon=True).start()


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

    logging.getLogger().setLevel(
        getattr(logging, cfg.get("log_level", "INFO").upper(), logging.INFO)
    )

    base = os.path.dirname(os.path.abspath(__file__))
    spec = load_spec(os.path.join(base, cfg["iso_spec"]))
    pans = load_pans(cfg)

    from_connections = {}
    from_lock = threading.Lock()

    cmd = CommandServer(cfg["command_port"], stats, stop_event)
    cmd.start()

    to_srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    to_srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    to_srv.bind(("", cfg["to_downstream_port"]))
    to_srv.listen(5)

    from_srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    from_srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    from_srv.bind(("", cfg["from_downstream_port"]))
    from_srv.listen(5)

    log.info("downstream_host: to_port=%d from_port=%d command=%d",
             cfg["to_downstream_port"], cfg["from_downstream_port"], cfg["command_port"])

    threading.Thread(
        target=_accept_loop,
        args=(to_srv, stop_event, _handle_to_conn, spec, pans, from_connections, from_lock, stats),
        name="to-acceptor",
        daemon=True,
    ).start()
    threading.Thread(
        target=_accept_loop,
        args=(from_srv, stop_event, _handle_from_conn, from_connections, from_lock, stats),
        name="from-acceptor",
        daemon=True,
    ).start()

    try:
        stop_event.wait()
    finally:
        to_srv.close()
        from_srv.close()
        log.info("downstream_host stopped")


if __name__ == "__main__":
    run()

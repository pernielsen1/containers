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
from shared.iso_utils import load_spec, f47_decode, hex_dump, build_0810
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


def _handle_from_conn(conn, addr, client_id, from_connections, from_lock, stats):
    """Register send queue for this client, then stream responses back to router."""
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


def _route_frame(client_id, transcode, iso_data, addr, spec, pans,
                 from_connections, from_lock, stats):
    """Process one request frame and put the encoded response on the matching from_conn queue."""
    if transcode == ims_connect.PING_TRANSCODE:
        log.info("downstream_host: PING received from %s, sending PIPES cleaned", addr)
        ping_resp = "PING".encode("cp500") + "PIPES cleaned".encode("cp500")
        with from_lock:
            send_q = from_connections.get(client_id)
        if send_q is not None:
            send_q.put(ping_resp)
        return

    if not iso_data:
        return

    stats.record_recv()
    hex_dump(f"RECV {addr}", iso_data, log)

    try:
        req, _ = iso8583.decode(iso_data, spec=spec)
    except Exception as e:
        log.warning("Decode error from %s: %s", addr, e)
        return

    mti = req.get("t")

    if mti == "0800":
        try:
            encoded = build_0810(req.get("24", "100"), spec)
        except Exception as e:
            log.warning("downstream_host: encode 0810 error: %s", e)
            return
        with from_lock:
            send_q = from_connections.get(client_id)
        if send_q is not None:
            send_q.put(encoded)
        log.debug("downstream_host: replied 0810 to %s", addr)
        return

    if mti != "0100":
        log.warning("Unexpected MTI %s from %s", mti, addr)
        return

    resp = _process_0100(req, pans)

    try:
        encoded, _ = iso8583.encode(resp, spec=spec)
    except Exception as e:
        log.warning("Encode error: %s", e)
        return

    with from_lock:
        send_q = from_connections.get(client_id)

    if send_q is None:
        log.warning("downstream_host: no from_conn for client_id=%s",
                    client_id.decode("cp500", errors="replace").rstrip())
        return

    send_q.put(encoded)


def _handle_to_conn(conn, addr, client_id, first_transcode, first_iso_data,
                    spec, pans, from_connections, from_lock, stats):
    """Process IMS-framed 0100 messages; first frame already read by dispatcher."""
    try:
        _route_frame(client_id, first_transcode, first_iso_data, addr,
                     spec, pans, from_connections, from_lock, stats)
        while True:
            try:
                _, cid, transcode, iso_data = ims_connect.read_request(conn)
            except ConnectionError:
                log.info("downstream_host: to_conn %s disconnected", addr)
                return
            _route_frame(cid, transcode, iso_data, addr,
                         spec, pans, from_connections, from_lock, stats)
    finally:
        conn.close()


def _handle_new_conn(conn, addr, spec, pans, from_connections, from_lock, stats):
    """Dispatcher: first IMS frame determines whether this is a from-conn or to-conn."""
    try:
        irm_f0, client_id, transcode, iso_data = ims_connect.read_request(conn)
    except ConnectionError as e:
        log.warning("downstream_host: %s handshake failed: %s", addr, e)
        conn.close()
        return

    if irm_f0 == 0x80:
        _handle_from_conn(conn, addr, client_id, from_connections, from_lock, stats)
    else:
        _handle_to_conn(conn, addr, client_id, transcode, iso_data,
                        spec, pans, from_connections, from_lock, stats)


def _accept_loop(srv_sock, stop_event, handler, *args):
    while not stop_event.is_set():
        srv_sock.settimeout(1)
        try:
            conn, addr = srv_sock.accept()
        except socket.timeout:
            continue
        except OSError:
            return
        log.info("downstream_host: accepted %s", addr)
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

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("", cfg["port"]))
    srv.listen(10)
    log.info("downstream_host: port=%d command=%d", cfg["port"], cfg["command_port"])

    threading.Thread(
        target=_accept_loop,
        args=(srv, stop_event, _handle_new_conn, spec, pans, from_connections, from_lock, stats),
        name="acceptor",
        daemon=True,
    ).start()

    try:
        stop_event.wait()
    finally:
        srv.close()
        log.info("downstream_host stopped")


if __name__ == "__main__":
    run()

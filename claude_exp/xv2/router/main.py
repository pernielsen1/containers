#!/usr/bin/env python3
import json
import logging
import os
import queue
import socket
import threading

import iso8583
import requests
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared.framing import read_message, write_message
from shared.stats import Stats
from shared.command_server import CommandServer
from shared.iso_utils import load_spec, f47_decode, f47_encode, hex_dump
from shared import ims_connect

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

_stan_counter = 0
_stan_lock = threading.Lock()


def _next_stan():
    global _stan_counter
    with _stan_lock:
        _stan_counter += 1
        return str(_stan_counter % 1000000).zfill(6)


def _crypto_call(endpoint, crypto_cfg, pan, f47_str):
    url = f"http://{crypto_cfg['host']}:{crypto_cfg['port']}/{endpoint}"
    try:
        r = requests.post(url, json={"f2": pan, "f47": f47_str}, timeout=5)
        r.raise_for_status()
        return r.json().get("f47", f47_str)
    except Exception as e:
        log.warning("crypto call %s failed: %s", endpoint, e)
        return f47_str


def _process_request(req, up_conn, up_addr, to_sock, ims_cfg, spec,
                     crypto_cfg, pending, pending_lock, ds_write_lock, stats):
    pan = req.get("2", "")
    upstream_stan = req.get("11", "")
    router_stan = _next_stan()

    f47 = _crypto_call("validate_0100", crypto_cfg, pan, req.get("47", ""))

    fwd = dict(req)
    fwd["11"] = router_stan
    if f47:
        fwd["47"] = f47

    with pending_lock:
        pending[router_stan] = {"up_conn": up_conn, "upstream_stan": upstream_stan}

    try:
        encoded, _ = iso8583.encode(fwd, spec=spec)
        frame = ims_connect.build_frame(
            0x00, ims_cfg["irm_id"], ims_cfg["client_id"], fwd["t"], encoded
        )
        with ds_write_lock:
            to_sock.sendall(frame)
        stats.record_sent()
        log.debug("router: forwarded 0100 STAN %s→%s pan=%s", upstream_stan, router_stan, pan)
    except Exception as e:
        log.warning("router: downstream send error: %s", e)
        with pending_lock:
            pending.pop(router_stan, None)


def _worker(work_queue, to_sock, ims_cfg, spec, crypto_cfg,
            pending, pending_lock, ds_write_lock, stats):
    while True:
        item = work_queue.get()
        if item is None:
            break
        req, up_conn, up_addr = item
        try:
            _process_request(req, up_conn, up_addr, to_sock, ims_cfg, spec,
                             crypto_cfg, pending, pending_lock, ds_write_lock, stats)
        except Exception as e:
            log.warning("router: worker error for %s: %s", up_addr, e)
        finally:
            work_queue.task_done()


def _handle_upstream(up_conn, up_addr, up_framing, spec, work_queue, stats):
    log.info("router: upstream connected %s", up_addr)
    try:
        while True:
            try:
                data = read_message(up_conn, up_framing)
            except ConnectionError:
                log.info("router: upstream %s disconnected", up_addr)
                return

            stats.record_recv()
            hex_dump(f"RECV upstream {up_addr}", data, log)
            try:
                req, _ = iso8583.decode(data, spec=spec)
            except Exception as e:
                log.warning("router: decode error from %s: %s", up_addr, e)
                continue

            if req.get("t") != "0100":
                log.warning("router: unexpected MTI %s from %s", req.get("t"), up_addr)
                continue

            work_queue.put((req, up_conn, up_addr))
    finally:
        up_conn.close()


def _downstream_receiver(from_sock, up_framing, spec,
                         crypto_cfg, pending, pending_lock, stats):
    log.info("router: downstream receiver started")
    while True:
        try:
            data = ims_connect.read_response(from_sock)
        except ConnectionError:
            log.info("router: downstream disconnected")
            return

        stats.record_recv()
        hex_dump("RECV downstream", data, log)
        try:
            resp, _ = iso8583.decode(data, spec=spec)
        except Exception as e:
            log.warning("router: decode error from downstream: %s", e)
            continue

        if resp.get("t") != "0110":
            log.warning("router: unexpected MTI %s from downstream", resp.get("t"))
            continue

        router_stan = resp.get("11", "")
        with pending_lock:
            entry = pending.pop(router_stan, None)

        if entry is None:
            log.warning("router: no pending entry for STAN=%s", router_stan)
            continue

        pan = resp.get("2", "")
        f47 = _crypto_call("validate_0110", crypto_cfg, pan, resp.get("47", ""))

        fwd = dict(resp)
        fwd["11"] = entry["upstream_stan"]
        if f47:
            fwd["47"] = f47

        try:
            encoded, _ = iso8583.encode(fwd, spec=spec)
            write_message(entry["up_conn"], encoded, up_framing)
            stats.record_sent()
            log.debug("router: forwarded 0110 STAN %s→%s rc=%s",
                      router_stan, entry["upstream_stan"], resp.get("39"))
        except Exception as e:
            log.warning("router: upstream reply error: %s", e)


def _connect_downstream_ims(ds_cfg, ims_cfg):
    host = ds_cfg["host"]

    to_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    to_sock.connect((host, ds_cfg["to_downstream_port"]))
    log.info("router: connected to downstream to_port=%d", ds_cfg["to_downstream_port"])

    from_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    from_sock.connect((host, ds_cfg["from_downstream_port"]))
    log.info("router: connected to downstream from_port=%d", ds_cfg["from_downstream_port"])

    resume = ims_connect.build_frame(0x80, ims_cfg["irm_id"], ims_cfg["client_id"])
    from_sock.sendall(resume)
    log.info("router: sent resume TPIPE")

    return to_sock, from_sock


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

    logging.getLogger().setLevel(
        getattr(logging, cfg.get("log_level", "INFO").upper(), logging.INFO)
    )

    base = os.path.dirname(os.path.abspath(__file__))
    spec = load_spec(os.path.join(base, cfg["iso_spec"]))

    up_framing = cfg["upstream"]["framing"]
    crypto_cfg = cfg["crypto"]

    ims_cfg = {
        "irm_id":    ims_connect.to_ebcdic(cfg["downstream"]["irm_id"], 8),
        "client_id": ims_connect.to_ebcdic(cfg["downstream"]["client_id"], 8),
    }

    pending = {}
    pending_lock = threading.Lock()
    ds_write_lock = threading.Lock()
    work_queue = queue.Queue()

    to_sock, from_sock = _connect_downstream_ims(cfg["downstream"], ims_cfg)
    threading.Thread(
        target=_downstream_receiver,
        args=(from_sock, up_framing, spec, crypto_cfg, pending, pending_lock, stats),
        name="ds-receiver",
        daemon=True,
    ).start()

    n_workers = cfg.get("worker_threads", 8)
    for i in range(n_workers):
        threading.Thread(
            target=_worker,
            args=(work_queue, to_sock, ims_cfg, spec, crypto_cfg,
                  pending, pending_lock, ds_write_lock, stats),
            name=f"worker-{i}",
            daemon=True,
        ).start()
    log.info("router: started %d worker threads", n_workers)

    cmd = CommandServer(cfg["command_port"], stats, stop_event)
    cmd.start()

    srv_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv_sock.bind(("", cfg["upstream"]["port"]))
    srv_sock.listen(10)
    log.info("router: upstream on :%d  command on :%d", cfg["upstream"]["port"], cfg["command_port"])

    try:
        while not stop_event.is_set():
            srv_sock.settimeout(1)
            try:
                up_conn, up_addr = srv_sock.accept()
            except socket.timeout:
                continue
            threading.Thread(
                target=_handle_upstream,
                args=(up_conn, up_addr, up_framing, spec, work_queue, stats),
                name=f"up-{up_addr}",
                daemon=True,
            ).start()
    finally:
        for _ in range(n_workers):
            work_queue.put(None)
        srv_sock.close()
        to_sock.close()
        from_sock.close()
        log.info("router stopped")


if __name__ == "__main__":
    run()

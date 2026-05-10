#!/usr/bin/env python3
import argparse
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


def _process_request(req, up_conn, up_write_lock, up_addr, to_sock, ims_cfg, spec,
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
        pending[router_stan] = {
            "up_conn": up_conn,
            "up_write_lock": up_write_lock,
            "upstream_stan": upstream_stan,
        }

    try:
        encoded, _ = iso8583.encode(fwd, spec=spec)
    except Exception as e:
        log.warning("router: encode error: %s", e)
        with pending_lock:
            pending.pop(router_stan, None)
        return

    frame = ims_connect.build_frame(
        0x00, ims_cfg["irm_id"], ims_cfg["client_id"], fwd["t"], encoded
    )
    with ds_write_lock:
        to_sock.sendall(frame)  # OSError propagates to worker → triggers reconnect
    stats.record_sent()
    log.debug("router: forwarded 0100 STAN %s→%s pan=%s", upstream_stan, router_stan, pan)


def _worker(work_queue, to_sock, ims_cfg, spec, crypto_cfg,
            pending, pending_lock, ds_write_lock, stats, reconnect_event):
    while True:
        item = work_queue.get()
        if item is None:
            break
        req, up_conn, up_write_lock, up_addr = item
        try:
            _process_request(req, up_conn, up_write_lock, up_addr, to_sock, ims_cfg, spec,
                             crypto_cfg, pending, pending_lock, ds_write_lock, stats)
        except OSError as e:
            log.warning("router: downstream write failed for %s: %s", up_addr, e)
            reconnect_event.set()
        except Exception as e:
            log.warning("router: worker error for %s: %s", up_addr, e)
        finally:
            work_queue.task_done()


def _handle_upstream(up_conn, up_addr, up_framing, spec, work_queue,
                     up_write_lock, upstream_ref,
                     to_sock, ims_cfg, ds_write_lock,
                     pending, pending_lock, stats, reconnect_event):
    log.info("router: upstream connected %s", up_addr)
    try:
        while True:
            try:
                data = read_message(up_conn, up_framing)
            except ConnectionError:
                log.info("router: upstream %s disconnected", up_addr)
                reconnect_event.set()
                return

            stats.record_recv()
            hex_dump(f"RECV upstream {up_addr}", data, log)
            try:
                req, _ = iso8583.decode(data, spec=spec)
            except Exception as e:
                log.warning("router: decode error from %s: %s", up_addr, e)
                continue

            mti = req.get("t")
            if mti == "0100":
                work_queue.put((req, up_conn, up_write_lock, up_addr))
            elif mti == "0800":
                try:
                    encoded, _ = iso8583.encode(req, spec=spec)
                    frame = ims_connect.build_frame(
                        0x00, ims_cfg["irm_id"], ims_cfg["client_id"], req["t"], encoded
                    )
                    with ds_write_lock:
                        to_sock.sendall(frame)
                    log.debug("router: forwarded 0800 to downstream")
                except OSError as e:
                    log.warning("router: failed to forward 0800: %s", e)
                    reconnect_event.set()
                    return
            elif mti == "0810":
                log.warning("router: unexpected 0810 from upstream %s", up_addr)
            else:
                log.warning("router: unexpected MTI %s from %s", mti, up_addr)
    finally:
        upstream_ref["conn"] = None
        upstream_ref["lock"] = None
        up_conn.close()


def _downstream_receiver(from_sock, up_framing, spec,
                         crypto_cfg, pending, pending_lock,
                         upstream_ref, stats, reconnect_event):
    log.info("router: downstream receiver started")
    while True:
        try:
            data = ims_connect.read_response(from_sock)
        except ConnectionError:
            log.info("router: downstream disconnected")
            reconnect_event.set()
            return

        stats.record_recv()
        hex_dump("RECV downstream", data, log)

        if data[:4] == "PING".encode("cp500"):
            log.info("router: pipe-cleaner response: %s", data.hex())
            continue

        try:
            resp, _ = iso8583.decode(data, spec=spec)
        except Exception as e:
            log.warning("router: decode error from downstream: %s", e)
            continue

        mti = resp.get("t")

        if mti == "0810":
            up_conn = upstream_ref["conn"]
            up_lock = upstream_ref["lock"]
            if up_conn is None:
                log.warning("router: received 0810 but no upstream connected")
                continue
            try:
                encoded, _ = iso8583.encode(resp, spec=spec)
                with up_lock:
                    write_message(up_conn, encoded, up_framing)
                log.debug("router: forwarded 0810 to upstream")
            except Exception as e:
                log.warning("router: failed to forward 0810: %s", e)
            continue

        if mti != "0110":
            log.warning("router: unexpected MTI %s from downstream", mti)
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
            with entry["up_write_lock"]:
                write_message(entry["up_conn"], encoded, up_framing)
            stats.record_sent()
            log.debug("router: forwarded 0110 STAN %s→%s rc=%s",
                      router_stan, entry["upstream_stan"], resp.get("39"))
        except Exception as e:
            log.warning("router: upstream reply error: %s", e)


def _upstream_accept_loop(srv_sock, up_framing, spec, work_queue, upstream_ref,
                          to_sock, ims_cfg, ds_write_lock,
                          pending, pending_lock, stats, reconnect_event, stop_event):
    while not reconnect_event.is_set() and not stop_event.is_set():
        srv_sock.settimeout(1)
        try:
            up_conn, up_addr = srv_sock.accept()
        except socket.timeout:
            continue
        except OSError:
            return

        up_write_lock = threading.Lock()
        upstream_ref["conn"] = up_conn
        upstream_ref["lock"] = up_write_lock

        t = threading.Thread(
            target=_handle_upstream,
            args=(up_conn, up_addr, up_framing, spec, work_queue,
                  up_write_lock, upstream_ref, to_sock, ims_cfg, ds_write_lock,
                  pending, pending_lock, stats, reconnect_event),
            name=f"up-{up_addr}",
            daemon=True,
        )
        t.start()
        t.join()  # one upstream connection at a time


def _client_upstream_loop(up_cfg, up_framing, spec, work_queue, upstream_ref,
                          to_sock, ims_cfg, ds_write_lock,
                          pending, pending_lock, stats, reconnect_event, stop_event):
    host = up_cfg["host"]
    port = up_cfg["port"]
    retry = up_cfg.get("retry_seconds", 5)
    while not reconnect_event.is_set() and not stop_event.is_set():
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((host, port))
        except OSError as e:
            log.info("router: upstream %s:%d unavailable (%s), retrying in %ds",
                     host, port, e, retry)
            stop_event.wait(timeout=retry)
            continue

        up_write_lock = threading.Lock()
        upstream_ref["conn"] = sock
        upstream_ref["lock"] = up_write_lock
        log.info("router: connected to upstream %s:%d", host, port)
        _handle_upstream(sock, (host, port), up_framing, spec, work_queue,
                         up_write_lock, upstream_ref, to_sock, ims_cfg,
                         ds_write_lock, pending, pending_lock, stats, reconnect_event)
        break  # disconnect already set reconnect_event


def _connect_downstream_ims(ds_cfg, ims_cfg):
    host = ds_cfg["host"]
    port = ds_cfg["port"]

    to_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    to_sock.connect((host, port))
    log.info("router: connected to downstream port=%d (to)", port)

    from_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    from_sock.connect((host, port))
    log.info("router: connected to downstream port=%d (from)", port)

    resume = ims_connect.build_frame(0x80, ims_cfg["irm_id"], ims_cfg["client_id"])
    from_sock.sendall(resume)
    log.info("router: sent resume TPIPE")

    ping_data = "1234 clean the pipes".encode("cp500")
    ping_frame = ims_connect.build_frame(
        0x00, ims_cfg["irm_id"], ims_cfg["client_id"],
        transcode=ims_connect.PING_TRANSCODE, data=ping_data,
    )
    to_sock.sendall(ping_frame)
    log.info("router: sent pipe-cleaner ping")

    return to_sock, from_sock


def load_config(path=None):
    if path is None:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "router_1", "config.json")
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

    up_cfg = cfg["upstream"]
    up_framing = up_cfg["framing"]
    up_mode = up_cfg.get("mode", "server")
    crypto_cfg = cfg["crypto"]
    reestablish_seconds = cfg.get("reestablish_seconds", 10)

    ims_cfg = {
        "irm_id":    ims_connect.to_ebcdic(cfg["downstream"]["irm_id"], 8),
        "client_id": ims_connect.to_ebcdic(cfg["downstream"]["client_id"], 8),
    }

    n_workers = cfg.get("worker_threads", 8)

    cmd = CommandServer(cfg["command_port"], stats, stop_event)
    cmd.start()

    srv_sock = None
    if up_mode == "server":
        srv_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv_sock.bind(("", up_cfg["port"]))
        srv_sock.listen(10)
        log.info("router: upstream server on :%d  command on :%d",
                 up_cfg["port"], cfg["command_port"])
    else:
        log.info("router: upstream client → %s:%d  command on :%d",
                 up_cfg["host"], up_cfg["port"], cfg["command_port"])

    try:
        while not stop_event.is_set():
            reconnect_event = threading.Event()
            upstream_ref = {"conn": None, "lock": None}
            pending = {}
            pending_lock = threading.Lock()
            ds_write_lock = threading.Lock()
            work_queue = queue.Queue()

            try:
                to_sock, from_sock = _connect_downstream_ims(cfg["downstream"], ims_cfg)
            except OSError as e:
                log.warning("router: downstream unavailable (%s), retrying in %ds",
                            e, reestablish_seconds)
                stop_event.wait(timeout=reestablish_seconds)
                continue

            threading.Thread(
                target=_downstream_receiver,
                args=(from_sock, up_framing, spec, crypto_cfg,
                      pending, pending_lock, upstream_ref, stats, reconnect_event),
                name="ds-receiver",
                daemon=True,
            ).start()

            for i in range(n_workers):
                threading.Thread(
                    target=_worker,
                    args=(work_queue, to_sock, ims_cfg, spec, crypto_cfg,
                          pending, pending_lock, ds_write_lock, stats, reconnect_event),
                    name=f"worker-{i}",
                    daemon=True,
                ).start()
            log.info("router: started %d worker threads", n_workers)

            if up_mode == "client":
                up_thread = threading.Thread(
                    target=_client_upstream_loop,
                    args=(up_cfg, up_framing, spec, work_queue, upstream_ref,
                          to_sock, ims_cfg, ds_write_lock, pending, pending_lock,
                          stats, reconnect_event, stop_event),
                    name="up-client",
                    daemon=True,
                )
            else:
                up_thread = threading.Thread(
                    target=_upstream_accept_loop,
                    args=(srv_sock, up_framing, spec, work_queue, upstream_ref,
                          to_sock, ims_cfg, ds_write_lock, pending, pending_lock,
                          stats, reconnect_event, stop_event),
                    name="up-server",
                    daemon=True,
                )
            up_thread.start()

            while not reconnect_event.is_set() and not stop_event.is_set():
                stop_event.wait(timeout=1)

            # teardown current session
            if upstream_ref["conn"]:
                try:
                    upstream_ref["conn"].close()
                except OSError:
                    pass
            for _ in range(n_workers):
                work_queue.put(None)
            try:
                to_sock.close()
            except OSError:
                pass
            try:
                from_sock.close()
            except OSError:
                pass

            up_thread.join(timeout=5)

            if stop_event.is_set():
                break

            log.info("router: session ended, reconnecting in %ds", reestablish_seconds)
            stop_event.wait(timeout=reestablish_seconds)

    finally:
        if srv_sock:
            srv_sock.close()
        log.info("router stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None, help="Path to config.json")
    args = parser.parse_args()
    cfg, config_base = load_config(args.config)
    run(cfg=cfg, _config_base=config_base)

#!/usr/bin/env python3
"""ISO 8583 authorization test utility."""

import argparse
import csv
import json
import logging
import os
import queue
import socket
import ssl
import struct
import sys
import threading
import time
from typing import Optional

import iso8583
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "tcp_framing": "TCP_framing_standard",
    "client": {
        "connect_timeout": 60,
        "batch_size": 50,
        "batch_wait": 10,
        "send_delay": 0.05,
        "ssl": {"enabled": False},
    },
    "server": {
        "idle_timeout": 120,
        "ssl": {"enabled": False},
    },
}


def load_config() -> dict:
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "config.json")
    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_CONFIG.items()}
    if os.path.exists(path):
        with open(path) as f:
            file_cfg = json.load(f)
        if "tcp_framing" in file_cfg:
            cfg["tcp_framing"] = file_cfg["tcp_framing"]
        for role in ("client", "server"):
            if role in file_cfg:
                cfg[role].update(file_cfg[role])
    return cfg


def load_spec(cfg: dict, role: str) -> dict:
    base = os.path.dirname(os.path.abspath(__file__))
    spec_file = cfg[role].get("iso_spec", "test_spec.json")
    spec_path = os.path.join(base, spec_file)
    with open(spec_path) as f:
        return json.load(f)


def _build_ssl_context(role: str, ssl_cfg: dict) -> Optional[ssl.SSLContext]:
    if not ssl_cfg.get("enabled"):
        return None
    if role == "server":
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=ssl_cfg["certfile"], keyfile=ssl_cfg.get("keyfile"))
        if ssl_cfg.get("cafile"):
            ctx.load_verify_locations(ssl_cfg["cafile"])
            ctx.verify_mode = ssl.CERT_REQUIRED
    else:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        if not ssl_cfg.get("verify", True):
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        elif ssl_cfg.get("cafile"):
            ctx.load_verify_locations(ssl_cfg["cafile"])
        if ssl_cfg.get("certfile"):
            ctx.load_cert_chain(ssl_cfg["certfile"], ssl_cfg.get("keyfile"))
    return ctx


# ── TCP framing ───────────────────────────────────────────────────────────────
# TCP_framing_standard  : 4-byte big-endian uint32 length + data
# TCP_framing_FFFF_nnnn : 0xFFFFFFFF marker + 4 ASCII digit length + data

_FFFF_MARKER = b"\xff\xff\xff\xff"

def _recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except OSError:
            return None
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def send_frame(sock: socket.socket, data: bytes, framing: str) -> None:
    if framing == "TCP_framing_FFFF_nnnn":
        sock.sendall(_FFFF_MARKER + f"{len(data):04d}".encode("ascii") + data)
    else:
        sock.sendall(struct.pack(">I", len(data)) + data)


def recv_frame(sock: socket.socket, framing: str) -> Optional[bytes]:
    if framing == "TCP_framing_FFFF_nnnn":
        marker = _recv_exact(sock, 4)
        if marker is None:
            return None
        if marker != _FFFF_MARKER:
            log.warning("recv_frame: expected FFFF marker, got %s", marker.hex())
            return None
        length_bytes = _recv_exact(sock, 4)
        if length_bytes is None:
            return None
        length = int(length_bytes.decode("ascii"))
    else:
        header = _recv_exact(sock, 4)
        if header is None:
            return None
        length = struct.unpack(">I", header)[0]
    return _recv_exact(sock, length)


def hex_dump(direction: str, length: int, data: bytes) -> None:
    hex_str = " ".join(f"{b:02x}" for b in data)
    log.debug("%s Length: %d | %s", direction, length, hex_str)


# ── Stats ──────────────────────────────────────────────────────────────────────

class Stats:
    def __init__(self):
        self._lock = threading.Lock()
        self.sent = 0
        self.received = 0
        self.approved = 0
        self.declined = 0
        self.errors = 0

    def inc(self, **kwargs):
        with self._lock:
            for k, v in kwargs.items():
                setattr(self, k, getattr(self, k) + v)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(
                sent=self.sent,
                received=self.received,
                approved=self.approved,
                declined=self.declined,
                errors=self.errors,
            )


# ── Client ─────────────────────────────────────────────────────────────────────

def run_client(args, cfg: dict, spec: dict, framing: str, verbose: bool = True) -> None:
    binary_fields = frozenset(k for k, v in spec.items() if v.get("data_enc") == "b")
    auto_fields = frozenset({"h", "p", "1"}) | binary_fields
    stats = Stats()
    ssl_ctx = _build_ssl_context("client", cfg["client"].get("ssl", {}))

    conn: Optional[socket.socket] = None
    deadline = time.monotonic() + cfg["client"]["connect_timeout"]
    while time.monotonic() < deadline:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)
            s.connect((args.host, args.port))
            if ssl_ctx:
                s = ssl_ctx.wrap_socket(s, server_hostname=args.host)
            s.settimeout(None)
            conn = s
            log.info("Connected to %s:%d%s", args.host, args.port, " (TLS)" if ssl_ctx else "")
            break
        except OSError as exc:
            log.debug("Connect failed: %s — retrying in 1s", exc)
            time.sleep(1)

    if conn is None:
        log.error("Could not connect within %ds", cfg["client"]["connect_timeout"])
        sys.exit(1)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    input_dir = os.path.join(base_dir, cfg["client"].get("input_dir", "input"))
    output_dir = os.path.join(base_dir, cfg["client"].get("output_dir", "output"))
    os.makedirs(output_dir, exist_ok=True)
    df = pd.read_csv(
        os.path.join(input_dir, "test_cases.csv"),
        sep=";",
        dtype=str,
    ).fillna("")

    # Only columns that map to valid (non-auto, non-binary) spec fields
    valid_cols = [c for c in df.columns if c in spec and c not in auto_fields]

    pending: dict = {}       # stan -> original row dict
    pending_lock = threading.Lock()
    results: list = []
    results_lock = threading.Lock()
    send_done = threading.Event()
    all_done = threading.Event()
    stan_seq = [0]

    def receive_thread():
        while True:
            data = recv_frame(conn, framing)
            if data is None:
                all_done.set()
                break
            if verbose:
                hex_dump("RECV", len(data), data)
            try:
                resp = iso8583.decode(data, spec=spec)[0]
            except Exception as exc:
                log.warning("Decode error: %s", exc)
                stats.inc(errors=1)
                continue

            stats.inc(received=1)
            ref = resp.get("63", "")
            rc = resp.get("39", "")
            if rc == "00":
                stats.inc(approved=1)
            else:
                stats.inc(declined=1)
            log.debug("Response F63=%s RC=%s auth=%s", ref, rc, resp.get("38", ""))

            with pending_lock:
                req_row = pending.pop(ref, {})

            row = dict(req_row)
            for k, v in resp.items():
                row[f"resp_{k}"] = v
            with results_lock:
                results.append(row)

            if send_done.is_set():
                with pending_lock:
                    if not pending:
                        all_done.set()

    def send_thread():
        batch_size = cfg["client"]["batch_size"]
        batch_wait = cfg["client"]["batch_wait"]
        send_delay = cfg["client"]["send_delay"]

        for i, (_, row) in enumerate(df.iterrows()):
            stan_seq[0] += 1
            stan = str(stan_seq[0]).zfill(6)

            doc: dict = {}
            for col in valid_cols:
                val = str(row[col]).strip()
                if val:
                    field_spec = spec.get(col, {})
                    if field_spec.get("len_type", -1) == 0 and field_spec.get("data_enc") != "b":
                        val = val.zfill(field_spec["max_len"])
                    doc[col] = val
            doc["11"] = stan
            ref = str(row.get("63", "")).strip()

            with pending_lock:
                pending[ref] = dict(row)

            try:
                encoded, _ = iso8583.encode(doc, spec=spec)
                send_frame(conn, encoded, framing)
                stats.inc(sent=1)
                log.debug("Sent STAN=%s F63=%s", stan, ref)
            except Exception as exc:
                log.warning("Encode/send error STAN=%s: %s", stan, exc)
                stats.inc(errors=1)
                with pending_lock:
                    pending.pop(ref, None)

            if (i + 1) % batch_size == 0:
                log.info("Sent %d messages — pausing %ds", i + 1, batch_wait)
                time.sleep(batch_wait)
            elif send_delay:
                time.sleep(send_delay)

        send_done.set()
        log.info("All %d messages sent", len(df))
        with pending_lock:
            if not pending:
                all_done.set()

    rt = threading.Thread(target=receive_thread, name="receive", daemon=True)
    st = threading.Thread(target=send_thread, name="send", daemon=True)
    rt.start()
    st.start()

    all_done.wait(timeout=20)
    log.info("Session complete. Stats: %s", stats.snapshot())
    conn.close()

    results_path = os.path.join(output_dir, "results.csv")
    with results_lock:
        if not results:
            log.warning("No results to write")
            return
        all_keys: list = []
        seen: set = set()
        for r in results:
            for k in r.keys():
                if k not in seen:
                    all_keys.append(k)
                    seen.add(k)
        with open(results_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(
                f, fieldnames=all_keys, delimiter=";", extrasaction="ignore"
            )
            writer.writeheader()
            for r in results:
                writer.writerow(r)
    log.info("Wrote %d results to %s", len(results), results_path)

    mismatches = [
        r for r in results
        if str(r.get("expected_39", "")).strip() != str(r.get("resp_39", "")).strip()
    ]
    if mismatches:
        mismatches_path = os.path.join(output_dir, "errors.csv")
        mismatch_keys: list = []
        seen2: set = set()
        for r in mismatches:
            for k in r.keys():
                if k not in seen2:
                    mismatch_keys.append(k)
                    seen2.add(k)
        with open(mismatches_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(
                f, fieldnames=mismatch_keys, delimiter=";", extrasaction="ignore"
            )
            writer.writeheader()
            for r in mismatches:
                writer.writerow(r)
        log.info("Wrote %d errors to %s", len(mismatches), mismatches_path)
    else:
        log.info("All responses matched expected_39")


# ── Server ─────────────────────────────────────────────────────────────────────

def _load_positive_list(cfg: dict) -> list:
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, cfg["server"].get("positive_list", "positive_list.json"))
    with open(path) as f:
        return json.load(f)["starts_with"]


def run_server(args, cfg: dict, spec: dict, framing: str, verbose: bool = True) -> None:
    positive_prefixes = _load_positive_list(cfg)
    log.info("Positive list: %s", positive_prefixes)
    stats = Stats()
    ssl_ctx = _build_ssl_context("server", cfg["server"].get("ssl", {}))

    srv_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv_sock.bind(("", args.port))
    srv_sock.listen(1)
    log.info("Server listening on :%d%s", args.port, " (TLS)" if ssl_ctx else "")

    idle_timeout = cfg["server"]["idle_timeout"]
    auth_counter = [0]
    auth_lock = threading.Lock()
    last_rx = [time.monotonic()]   # updated on every inbound message
    shutdown_ev = threading.Event()

    def _watchdog():
        while not shutdown_ev.is_set():
            time.sleep(1)
            if time.monotonic() - last_rx[0] > idle_timeout:
                log.info("No inbound messages for %ds — shutting down", idle_timeout)
                shutdown_ev.set()

    threading.Thread(target=_watchdog, name="watchdog", daemon=True).start()

    while not shutdown_ev.is_set():
        srv_sock.settimeout(1)
        try:
            conn, addr = srv_sock.accept()
            if ssl_ctx:
                conn = ssl_ctx.wrap_socket(conn, server_side=True)
        except (socket.timeout, ssl.SSLError) as exc:
            if not isinstance(exc, socket.timeout):
                log.warning("TLS handshake failed from %s: %s", addr if 'addr' in dir() else '?', exc)
            continue

        log.debug("Client connected from %s%s", addr, " (TLS)" if ssl_ctx else "")
        send_q: queue.Queue = queue.Queue()
        stop_ev = threading.Event()

        def _receive(conn=conn, send_q=send_q, stop_ev=stop_ev):
            while not stop_ev.is_set():
                data = recv_frame(conn, framing)
                if data is None:
                    log.info("Client disconnected")
                    stop_ev.set()
                    send_q.put(None)
                    break

                last_rx[0] = time.monotonic()
                if verbose:
                    hex_dump("RECV", len(data), data)
                stats.inc(received=1)
                try:
                    req = iso8583.decode(data, spec=spec)[0]
                except Exception as exc:
                    log.warning("Decode error: %s", exc)
                    stats.inc(errors=1)
                    continue

                pan = req.get("2", "")
                resp: dict = {}

                mti = req.get("t", "")
                if mti == "0100":
                    resp["t"] = "0110"
                else:
                    log.warning("Unexpected MTI %s", mti)
                    continue

                # Echo STAN and key request fields
                for fld in ("2", "3", "4", "11", "37", "41", "42", "63"):
                    if fld in req:
                        resp[fld] = req[fld]

                if any(pan.startswith(p) for p in positive_prefixes):
                    with auth_lock:
                        auth_counter[0] += 1
                        auth_code = str(auth_counter[0]).zfill(6)
                    resp["39"] = "00"
                    resp["38"] = auth_code
                    stats.inc(approved=1)
                    log.debug("Approved PAN=%s auth=%s", pan, auth_code)
                else:
                    resp["39"] = "01"
                    stats.inc(declined=1)
                    log.debug("Declined PAN=%s", pan)

                send_q.put(resp)

        def _send(conn=conn, send_q=send_q):
            while True:
                item = send_q.get()
                if item is None:
                    break
                try:
                    encoded, _ = iso8583.encode(item, spec=spec)
                    send_frame(conn, encoded, framing)
                    stats.inc(sent=1)
                except Exception as exc:
                    log.warning("Send error: %s", exc)
                    stats.inc(errors=1)

        rt = threading.Thread(target=_receive, name="srv-receive", daemon=True)
        st = threading.Thread(target=_send, name="srv-send", daemon=True)
        rt.start()
        st.start()

        stop_ev.wait()
        conn.close()
        rt.join(timeout=5)
        st.join(timeout=5)
        log.info("Client session ended. Stats: %s", stats.snapshot())

    srv_sock.close()
    log.info("Server stopped")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ISO 8583 authorization test utility")
    parser.add_argument("role", choices=["client", "server"])
    parser.add_argument("--port", type=int, default=1042)
    parser.add_argument("--host", default="localhost", help="Server host (client only)")
    parser.add_argument("--framing", default=None,
                        choices=["TCP_framing_standard", "TCP_framing_FFFF_nnnn"],
                        help="TCP framing scheme (overrides config.json)")
    parser.add_argument("--verbose", default=True, action=argparse.BooleanOptionalAction,
                        help="Show hex dump of every message (default: on)")
    parser.add_argument("--log-level", default=None,
                        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                        help="Log level (overrides config.json)")
    args = parser.parse_args()

    cfg = load_config()
    level = args.log_level or cfg.get("log_level", "INFO")
    logging.getLogger().setLevel(level)
    spec = load_spec(cfg, args.role)
    framing = args.framing if args.framing else cfg.get("tcp_framing", "TCP_framing_standard")
    log.info("TCP framing: %s", framing)

    if args.role == "client":
        run_client(args, cfg, spec, framing, verbose=args.verbose)
    else:
        run_server(args, cfg, spec, framing, verbose=args.verbose)


if __name__ == "__main__":
    main()

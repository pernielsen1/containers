#!/usr/bin/env python3
"""ISO 8583 authorization test utility."""

import argparse
import csv
import json
import logging
import os
import queue
import socket
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

import iso8583
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iso_spec import test_spec

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# Fields auto-managed by pyiso8583 or binary-encoded — skip when reading CSV
_BINARY_FIELDS = frozenset(k for k, v in test_spec.items() if v.get("data_enc") == "b")
_AUTO_FIELDS = frozenset({"h", "p", "1"}) | _BINARY_FIELDS

DEFAULT_CONFIG = {
    "client": {
        "connect_timeout": 60,
        "batch_size": 50,
        "batch_wait": 10,
        "send_delay": 0.05,
    },
    "server": {
        "idle_timeout": 120,
    },
}


def load_config() -> dict:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    cfg = {k: dict(v) for k, v in DEFAULT_CONFIG.items()}
    if os.path.exists(path):
        with open(path) as f:
            file_cfg = json.load(f)
        for role in ("client", "server"):
            if role in file_cfg:
                cfg[role].update(file_cfg[role])
    return cfg


# ── TCP framing (32-bit big-endian length prefix) ─────────────────────────────

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


def send_frame(sock: socket.socket, data: bytes) -> None:
    sock.sendall(struct.pack(">I", len(data)) + data)


def recv_frame(sock: socket.socket) -> Optional[bytes]:
    header = _recv_exact(sock, 4)
    if header is None:
        return None
    length = struct.unpack(">I", header)[0]
    return _recv_exact(sock, length)


def hex_dump(direction: str, length: int, data: bytes) -> None:
    hex_str = " ".join(f"{b:02x}" for b in data)
    log.info("%s Length: %d | %s", direction, length, hex_str)


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


# ── Web command server ─────────────────────────────────────────────────────────

def make_handler(stats: Stats, role: str):
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            s = stats.snapshot()
            rows = "".join(
                f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in s.items()
            )
            body = (
                f'<!DOCTYPE html><html><head><title>ISO8583 {role}</title>'
                f'<meta http-equiv="refresh" content="2"></head>'
                f"<body><h2>ISO 8583 Test &mdash; {role.upper()}</h2>"
                f'<table border="1" cellpadding="4">'
                f"<tr><th>Metric</th><th>Value</th></tr>{rows}"
                f"</table></body></html>"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    return _Handler


def start_command_server(stats: Stats, role: str, port: int) -> None:
    server = HTTPServer(("localhost", port), make_handler(stats, role))
    t = threading.Thread(target=server.serve_forever, name="command", daemon=True)
    t.start()
    log.info("Command web server: http://localhost:%d", port)


# ── Client ─────────────────────────────────────────────────────────────────────

def run_client(args, cfg: dict, verbose: bool = True) -> None:
    stats = Stats()
    start_command_server(stats, "client", args.command_port)

    conn: Optional[socket.socket] = None
    deadline = time.monotonic() + cfg["client"]["connect_timeout"]
    while time.monotonic() < deadline:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)
            s.connect((args.host, args.port))
            s.settimeout(None)
            conn = s
            log.info("Connected to %s:%d", args.host, args.port)
            break
        except OSError as exc:
            log.debug("Connect failed: %s — retrying in 1s", exc)
            time.sleep(1)

    if conn is None:
        log.error("Could not connect within %ds", cfg["client"]["connect_timeout"])
        sys.exit(1)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    df = pd.read_csv(
        os.path.join(base_dir, "test_cases.csv"),
        sep=";",
        dtype=str,
    ).fillna("")

    # Only columns that map to valid (non-auto, non-binary) spec fields
    valid_cols = [c for c in df.columns if c in test_spec and c not in _AUTO_FIELDS]

    pending: dict = {}       # stan -> original row dict
    pending_lock = threading.Lock()
    results: list = []
    results_lock = threading.Lock()
    send_done = threading.Event()
    all_done = threading.Event()
    stan_seq = [0]

    def receive_thread():
        while True:
            data = recv_frame(conn)
            if data is None:
                all_done.set()
                break
            if verbose:
                hex_dump("RECV", len(data), data)
            try:
                resp = iso8583.decode(data, spec=test_spec)[0]
            except Exception as exc:
                log.warning("Decode error: %s", exc)
                stats.inc(errors=1)
                continue

            stats.inc(received=1)
            stan = resp.get("11", "")
            rc = resp.get("39", "")
            if rc == "00":
                stats.inc(approved=1)
            else:
                stats.inc(declined=1)
            log.info("Response STAN=%s RC=%s auth=%s", stan, rc, resp.get("38", ""))

            with pending_lock:
                req_row = pending.pop(stan, {})

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
                    doc[col] = val
            doc["11"] = stan

            with pending_lock:
                pending[stan] = dict(row)

            try:
                encoded, _ = iso8583.encode(doc, spec=test_spec)
                send_frame(conn, encoded)
                stats.inc(sent=1)
                log.debug("Sent STAN=%s", stan)
            except Exception as exc:
                log.warning("Encode/send error STAN=%s: %s", stan, exc)
                stats.inc(errors=1)
                with pending_lock:
                    pending.pop(stan, None)

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

    results_path = os.path.join(base_dir, "results.csv")
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


# ── Server ─────────────────────────────────────────────────────────────────────

def run_server(args, cfg: dict, verbose: bool = True) -> None:
    stats = Stats()
    start_command_server(stats, "server", args.command_port)

    srv_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv_sock.bind(("", args.port))
    srv_sock.listen(1)
    log.info("Server listening on :%d", args.port)

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
        except socket.timeout:
            continue

        log.info("Client connected from %s", addr)
        send_q: queue.Queue = queue.Queue()
        stop_ev = threading.Event()

        def _receive(conn=conn, send_q=send_q, stop_ev=stop_ev):
            while not stop_ev.is_set():
                data = recv_frame(conn)
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
                    req = iso8583.decode(data, spec=test_spec)[0]
                except Exception as exc:
                    log.warning("Decode error: %s", exc)
                    stats.inc(errors=1)
                    continue

                pan = req.get("2", "")
                resp: dict = {}

                # Response MTI: set bit 1 of 3rd nibble (0100 → 0110)
                mti = req.get("t", "0100")
                resp["t"] = mti[:2] + "1" + mti[3]

                # Echo STAN and key request fields
                for fld in ("2", "3", "4", "11", "37", "41", "42"):
                    if fld in req:
                        resp[fld] = req[fld]

                if pan.startswith("543210"):
                    with auth_lock:
                        auth_counter[0] += 1
                        auth_code = str(auth_counter[0]).zfill(6)
                    resp["39"] = "00"
                    resp["38"] = auth_code
                    stats.inc(approved=1)
                    log.info("Approved PAN=%s auth=%s", pan, auth_code)
                else:
                    resp["39"] = "01"
                    stats.inc(declined=1)
                    log.info("Declined PAN=%s", pan)

                send_q.put(resp)

        def _send(conn=conn, send_q=send_q):
            while True:
                item = send_q.get()
                if item is None:
                    break
                try:
                    encoded, _ = iso8583.encode(item, spec=test_spec)
                    send_frame(conn, encoded)
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
    parser.add_argument("--command_port", type=int, default=None,
                        help="Web command port (default: 1043 server, 1044 client)")
    parser.add_argument("--verbose", default=True, action=argparse.BooleanOptionalAction,
                        help="Show hex dump of every message (default: on)")
    args = parser.parse_args()

    if args.command_port is None:
        args.command_port = 1043 if args.role == "server" else 1044

    cfg = load_config()

    if args.role == "client":
        run_client(args, cfg, verbose=args.verbose)
    else:
        run_server(args, cfg, verbose=args.verbose)


if __name__ == "__main__":
    main()

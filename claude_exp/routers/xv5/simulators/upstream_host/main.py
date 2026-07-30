import argparse
import csv
import json
import logging
import os
import socket
import sys
import threading
import time
from itertools import count

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import iso8583  # noqa: E402
from flask import jsonify, request  # noqa: E402

from shared.command_server import CommandServer  # noqa: E402
from shared.framing import read_message, write_message  # noqa: E402
from shared.iso_utils import build_0800, load_spec  # noqa: E402
from shared.stats import Stats  # noqa: E402

logger = logging.getLogger(__name__)

_STAN_MODULUS = 1_000_000
_RESPONSE_MTIS = ("0110", "0130", "0430")


def load_config(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    with open(path) as f:
        cfg = json.load(f)
    base_dir = os.path.dirname(os.path.abspath(path))
    cfg["iso_spec"] = os.path.normpath(os.path.join(base_dir, cfg["iso_spec"]))
    cfg["input_dir"] = os.path.normpath(os.path.join(base_dir, cfg.get("input_dir", "input")))
    return cfg


class UpstreamHostSim:
    """Simulates an upstream card network client."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.spec = load_spec(cfg["iso_spec"])
        self.framing = cfg["framing"]
        self.mode = cfg.get("mode", "client")
        self.ping_0800_seconds = cfg.get("ping_0800_seconds", 30)

        os.makedirs(cfg["input_dir"], exist_ok=True)

        self.stats = Stats(yellow_threshold_seconds=cfg.get("yellow_threshold_seconds"))
        self.stop_event = threading.Event()

        self._conn = None
        self._conn_lock = threading.Lock()

        self._stan_counter = count(1)

        self.pending = {}
        self.pending_lock = threading.Lock()
        self.results = []
        self.results_lock = threading.Lock()

        # Stress-run state: send timestamps keyed by STAN, and a bounded latency-sample list.
        # Capped at 200k - plenty for any run duration/rate used here, keeps memory bounded on a
        # long high-rate stress run instead of growing unboundedly.
        self._MAX_LATENCY_SAMPLES = 200_000
        self.send_times = {}
        self.latencies = []
        self.run_start_time = None
        self.run_end_time = None
        self.run_sent = 0

        self.cmd = CommandServer(cfg["command_port"], self.stats, self.stop_event)
        self._register_routes()
        self._listen_sock = None

    def _next_stan(self) -> str:
        stan = next(self._stan_counter) % _STAN_MODULUS
        return str(stan).zfill(6)

    def _csv_path(self) -> str:
        return os.path.join(self.cfg["input_dir"], "test_cases.csv")

    def _read_csv(self) -> list:
        with open(self._csv_path(), newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f, delimiter=";"))

    def _register_routes(self) -> None:
        @self.cmd.register("/upload", methods=["POST"])
        def upload():
            uploaded = request.files.get("file")
            if uploaded is None:
                return jsonify({"error": "no file provided"}), 400
            uploaded.save(self._csv_path())
            return jsonify({"status": "ok"})

        @self.cmd.register("/start", methods=["GET"])
        def start_route():
            try:
                rows = self._read_csv()
            except OSError:
                return jsonify({"error": "no CSV uploaded"}), 400

            conn = self._get_conn()
            if conn is None:
                return jsonify({"error": "not connected to router"}), 503

            # rate/duration are optional: omitted, this is the original one-pass-through-the-CSV
            # functional-test behavior at the legacy fixed 20ms pacing. Given, the send loop
            # instead cycles the CSV rows (wrapping back to row 0) at 1/rate intervals until
            # duration elapses - used by stress_run.sh, not by the functional run_test.sh.
            rate = request.args.get("rate", type=float)
            duration = request.args.get("duration", type=float)

            with self.pending_lock:
                self.pending.clear()
            self.send_times.clear()
            with self.results_lock:
                self.results.clear()
            self.latencies.clear()
            self.run_start_time = time.time()
            self.run_end_time = None
            self.run_sent = 0

            threading.Thread(
                target=self._send_loop, args=(conn, rows, rate, duration), daemon=True
            ).start()
            return jsonify({"rows": len(rows)})

        @self.cmd.register("/results", methods=["GET"])
        def results_route():
            with self.results_lock:
                return jsonify(list(self.results))

        @self.cmd.register("/stress_stats", methods=["GET"])
        def stress_stats_route():
            with self.results_lock:
                received = len(self.results)
            sent = self.run_sent
            end_time = self.run_end_time if self.run_end_time is not None else time.time()
            elapsed = (end_time - self.run_start_time) if self.run_start_time else 0.0
            samples = sorted(self.latencies)

            def percentile(p):
                if not samples:
                    return None
                idx = min(len(samples) - 1, int(round(p / 100.0 * (len(samples) - 1))))
                return round(samples[idx] * 1000, 2)

            return jsonify(
                {
                    "sent": sent,
                    "received": received,
                    "errors": max(0, sent - received),
                    "elapsed_s": round(elapsed, 2),
                    "achieved_tps": round(sent / elapsed, 2) if elapsed > 0 else 0,
                    "p50_ms": percentile(50),
                    "p95_ms": percentile(95),
                    "p99_ms": percentile(99),
                    "max_ms": round(samples[-1] * 1000, 2) if samples else None,
                }
            )

    def _get_conn(self):
        with self._conn_lock:
            return self._conn

    def _send_loop(self, conn, rows, rate=None, duration=None) -> None:
        interval = (1.0 / rate) if rate else 0.02
        deadline = (time.time() + duration) if duration else None
        # No duration: legacy one-pass-through-the-CSV functional-test behavior. With a
        # duration: cycle the (usually tiny) CSV rows to sustain load for the requested window -
        # used by stress_run.sh.
        row_iter = iter(rows)
        while not self.stop_event.is_set():
            row = next(row_iter, None)
            if row is None:
                if deadline is None:
                    break
                row_iter = iter(rows)
                row = next(row_iter, None)
                if row is None:
                    break
            if deadline is not None and time.time() >= deadline:
                break

            stan = self._next_stan()
            # Column names are ISO 8583 field numbers; non-matching columns (e.g. expected_39)
            # are silently ignored. Field 11 (STAN) is always overwritten by the sender.
            msg = {k: v for k, v in row.items() if k in self.spec and k not in ("t", "p", "1")}
            msg["t"] = "0100"
            msg["11"] = stan

            with self.pending_lock:
                self.pending[stan] = row
            self.send_times[stan] = time.time()

            try:
                encoded, _ = iso8583.encode(msg, self.spec)
                write_message(conn, bytes(encoded), self.framing)
                self.stats.record_sent()
                self.run_sent += 1
            except OSError:
                break
            time.sleep(interval)
        # Marks when active sending stopped, distinct from "now" - /stress_stats is queried
        # after a trailing grace window (letting in-flight responses land), and achieved_tps
        # must reflect the actual send window, not that grace window too.
        self.run_end_time = time.time()

    def _receive_loop(self, conn, disc_evt: threading.Event) -> None:
        while not disc_evt.is_set():
            try:
                data = read_message(conn, self.framing)
            except ConnectionError:
                disc_evt.set()
                break

            try:
                resp, _ = iso8583.decode(data, self.spec)
            except Exception:
                logger.exception("failed to decode router response")
                continue
            self.stats.record_recv()

            mti = resp.get("t")
            if mti == "0810":
                continue
            if mti not in _RESPONSE_MTIS:
                logger.warning("unexpected response MTI: %s", mti)
                continue

            stan = resp.get("11", "")
            with self.pending_lock:
                row = self.pending.pop(stan, None)
            if row is None:
                logger.warning("no pending request for STAN %s", stan)
                continue

            send_time = self.send_times.pop(stan, None)
            if send_time is not None and len(self.latencies) < self._MAX_LATENCY_SAMPLES:
                self.latencies.append(time.time() - send_time)

            merged = dict(row)
            for k, v in resp.items():
                merged[f"resp_{k}"] = v
            with self.results_lock:
                self.results.append(merged)

    def _keepalive_loop(self, conn, disc_evt: threading.Event) -> None:
        while not disc_evt.is_set() and not self.stop_event.is_set():
            try:
                write_message(conn, build_0800(self.spec), self.framing)
                self.stats.record_sent()
            except OSError:
                return
            # interruptible wait for the rest of the interval
            elapsed = 0.0
            while elapsed < self.ping_0800_seconds:
                if disc_evt.is_set() or self.stop_event.is_set():
                    return
                time.sleep(min(1.0, self.ping_0800_seconds - elapsed))
                elapsed += 1.0

    def _run_connection(self, sock) -> None:
        with self._conn_lock:
            self._conn = sock
        self.stats.set_connection("router", True)

        disc_evt = threading.Event()
        recv_thread = threading.Thread(target=self._receive_loop, args=(sock, disc_evt), daemon=True)
        recv_thread.start()
        keepalive_thread = threading.Thread(target=self._keepalive_loop, args=(sock, disc_evt), daemon=True)
        keepalive_thread.start()

        disc_evt.wait()

        with self._conn_lock:
            if self._conn is sock:
                self._conn = None
        self.stats.set_connection("router", False)
        try:
            sock.close()
        except OSError:
            pass
        recv_thread.join(timeout=2)
        keepalive_thread.join(timeout=2)

    def _client_connect_loop(self) -> None:
        router_cfg = self.cfg["router"]
        retry_seconds = self.cfg.get("retry_seconds", 5)
        while not self.stop_event.is_set():
            try:
                sock = socket.create_connection((router_cfg["host"], router_cfg["port"]), timeout=5)
                sock.settimeout(None)  # switch to blocking; timeout=5 above is connect-only
            except OSError:
                self.stop_event.wait(retry_seconds)
                continue
            self._run_connection(sock)

    def _server_accept_loop(self) -> None:
        router_cfg = self.cfg["router"]
        self._listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listen_sock.bind(("0.0.0.0", router_cfg["port"]))
        self._listen_sock.listen(5)
        self._listen_sock.settimeout(1.0)

        while not self.stop_event.is_set():
            try:
                conn, _addr = self._listen_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self._run_connection(conn)

    def start(self) -> None:
        self.cmd.start()
        if self.mode == "server":
            threading.Thread(target=self._server_accept_loop, daemon=True).start()
        else:
            threading.Thread(target=self._client_connect_loop, daemon=True).start()

    def run_forever(self) -> None:
        self.start()
        self.stop_event.wait()
        if self._listen_sock is not None:
            try:
                self._listen_sock.close()
            except OSError:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    args = parser.parse_args()

    cfg = load_config(args.config)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    sim = UpstreamHostSim(cfg)
    sim.run_forever()

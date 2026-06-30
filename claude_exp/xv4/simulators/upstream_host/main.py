import argparse
import csv
import io
import json
import logging
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import iso8583
import iso8583.specs
from flask import jsonify, request

from shared.command_server import CommandServer
from shared.framing import read_message, write_message
from shared.iso_utils import build_0800, load_spec
from shared.stats import Stats

logger = logging.getLogger(__name__)


class UpstreamHost:
    def __init__(self, cfg, spec, cfg_dir=None):
        self._cfg = cfg
        self._spec = spec
        self._framing = cfg["framing"]
        self._cfg_dir = cfg_dir or os.path.dirname(os.path.abspath(__file__))
        self.stats = Stats(yellow_threshold_seconds=cfg.get("yellow_threshold_seconds"))
        self.stop_event = threading.Event()

        self._conn = None
        self._conn_lock = threading.Lock()
        self._stan_counter = 0
        self._stan_lock = threading.Lock()
        self._pending = {}
        self._pending_lock = threading.Lock()
        self._results = []
        self._results_lock = threading.Lock()

    def _next_stan(self) -> str:
        with self._stan_lock:
            self._stan_counter = (self._stan_counter + 1) % 1_000_000
            return str(self._stan_counter).zfill(6)

    def _send_loop(self, conn, rows):
        for row in rows:
            if self.stop_event.is_set():
                break
            msg = {}
            for k, v in row.items():
                if k in self._spec and k not in ("expected_39",):
                    msg[k] = v
            stan = self._next_stan()
            msg["11"] = stan
            msg.setdefault("t", "0100")

            with self._pending_lock:
                self._pending[stan] = dict(row)

            try:
                encoded, _ = iso8583.encode(msg, self._spec)
                write_message(conn, encoded, self._framing)
                self.stats.record_sent()
            except Exception as e:
                logger.warning("send error: %s", e)
                with self._pending_lock:
                    self._pending.pop(stan, None)

            time.sleep(0.02)

    def _receive_loop(self, conn, disc_evt):
        while not disc_evt.is_set() and not self.stop_event.is_set():
            try:
                data = read_message(conn, self._framing)
            except ConnectionError as e:
                logger.info("receive loop disconnected: %s", e)
                disc_evt.set()
                break

            try:
                resp, _ = iso8583.decode(data, self._spec)
            except Exception as e:
                logger.warning("decode error: %s", e)
                continue

            mti = resp.get("t")
            if mti == "0810":
                self.stats.record_recv()
                continue

            stan = resp.get("11", "")
            self.stats.record_recv()

            with self._pending_lock:
                original = self._pending.pop(stan, {})

            result = dict(original)
            for k, v in resp.items():
                result[f"resp_{k}"] = v
            with self._results_lock:
                self._results.append(result)

    def _keepalive_loop(self, conn, disc_evt):
        while not disc_evt.is_set() and not self.stop_event.is_set():
            try:
                write_message(conn, build_0800(self._spec), self._framing)
                self.stats.record_sent()
            except OSError:
                return
            elapsed = 0.0
            ping_seconds = self._cfg.get("ping_0800_seconds", 30)
            while elapsed < ping_seconds:
                if disc_evt.is_set() or self.stop_event.is_set():
                    return
                time.sleep(min(1.0, ping_seconds - elapsed))
                elapsed += 1.0

    def _run_connection(self, sock):
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

    def _client_connect_loop(self):
        router_cfg = self._cfg["router"]
        retry_seconds = self._cfg.get("retry_seconds", 5)
        while not self.stop_event.is_set():
            try:
                sock = socket.create_connection(
                    (router_cfg["host"], router_cfg["port"]), timeout=5
                )
                sock.settimeout(None)
            except OSError:
                self.stop_event.wait(retry_seconds)
                continue
            self._run_connection(sock)

    def _server_loop(self):
        mode_cfg = self._cfg.get("server", {})
        port = mode_cfg.get("port", self._cfg.get("port", 5010))
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", port))
        srv.listen(5)
        srv.settimeout(1.0)
        while not self.stop_event.is_set():
            try:
                conn, _ = srv.accept()
                conn.settimeout(None)
                self._run_connection(conn)
            except socket.timeout:
                continue
            except OSError:
                break
        try:
            srv.close()
        except OSError:
            pass

    def start_connect_loop(self):
        mode = self._cfg.get("mode", "client")
        if mode == "server":
            t = threading.Thread(target=self._server_loop, daemon=True)
        else:
            t = threading.Thread(target=self._client_connect_loop, daemon=True)
        t.start()

    def start_send(self) -> int:
        input_dir = os.path.normpath(os.path.join(
            self._cfg_dir,
            self._cfg.get("input_dir", "input"),
        ))
        # Check instance-specific input dir first
        csv_path = os.path.join(input_dir, "test_cases.csv")
        if not os.path.exists(csv_path):
            logger.warning("no test_cases.csv at %s", csv_path)
            return 0

        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            rows = list(reader)

        with self._conn_lock:
            conn = self._conn

        if conn is None:
            return -1

        t = threading.Thread(target=self._send_loop, args=(conn, rows), daemon=True)
        t.start()
        return len(rows)

    def get_results(self):
        with self._results_lock:
            return list(self._results)

    def upload_csv(self, content: bytes, filename: str):
        input_dir = os.path.normpath(os.path.join(self._cfg_dir, self._cfg.get("input_dir", "input")))
        os.makedirs(input_dir, exist_ok=True)
        path = os.path.join(input_dir, "test_cases.csv")
        with open(path, "wb") as f:
            f.write(content)


def make_app(host_instance):
    cmd = CommandServer(
        port=host_instance._cfg["command_port"],
        stats=host_instance.stats,
        stop_event=host_instance.stop_event,
    )

    @cmd.register("/start", methods=("GET",))
    def start():
        n = host_instance.start_send()
        if n < 0:
            return jsonify({"error": "not connected to router"}), 503
        return jsonify({"rows": n})

    @cmd.register("/results", methods=("GET",))
    def results():
        return jsonify(host_instance.get_results())

    @cmd.register("/upload", methods=("POST",))
    def upload():
        f = request.files.get("file")
        if f is None:
            return jsonify({"error": "no file"}), 400
        host_instance.upload_csv(f.read(), f.filename)
        return jsonify({"status": "ok"})

    cmd.start()
    return cmd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    if args.config:
        cfg_path = os.path.abspath(args.config)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
        cfg_path = os.path.join(base, "config.json")

    with open(cfg_path) as f:
        cfg = json.load(f)

    cfg_dir = os.path.dirname(cfg_path)
    spec_path = os.path.normpath(os.path.join(cfg_dir, cfg["iso_spec"]))
    spec = load_spec(spec_path)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    host = UpstreamHost(cfg, spec, cfg_dir=cfg_dir)
    make_app(host)
    host.start_connect_loop()

    host.stop_event.wait()


if __name__ == "__main__":
    main()

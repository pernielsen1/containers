import argparse
import json
import logging
import os
import queue
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import iso8583  # noqa: E402

from shared.command_server import CommandServer  # noqa: E402
from shared.ims_connect import PING_TRANSCODE, read_request, write_response  # noqa: E402
from shared.iso_utils import f47_decode, f47_encode, load_spec  # noqa: E402
from shared.stats import Stats  # noqa: E402

logger = logging.getLogger(__name__)


def load_config(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    with open(path) as f:
        cfg = json.load(f)
    base_dir = os.path.dirname(os.path.abspath(path))
    cfg["iso_spec"] = os.path.normpath(os.path.join(base_dir, cfg["iso_spec"]))
    cfg["pans_defined"] = os.path.normpath(os.path.join(base_dir, cfg["pans_defined"]))
    return cfg


class DownstreamHostSim:
    """Simulates an IMS Connect authorization host."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.spec = load_spec(cfg["iso_spec"])
        with open(cfg["pans_defined"]) as f:
            self.pans = json.load(f)

        self.stats = Stats(yellow_threshold_seconds=cfg.get("yellow_threshold_seconds"))
        self.stop_event = threading.Event()

        self.from_connections = {}
        self.from_connections_lock = threading.Lock()

        self._auth_code_counter = 0
        self._auth_code_lock = threading.Lock()

        self.cmd = CommandServer(cfg["command_port"], self.stats, self.stop_event)
        self._listen_sock = None

    def _next_auth_code(self) -> str:
        with self._auth_code_lock:
            self._auth_code_counter += 1
            return str(self._auth_code_counter).zfill(6)

    def _wait_for_from_conn(self, client_id: bytes, timeout: float = 2.0):
        """Polls for up to `timeout` seconds. The from-conn's resume-TPIPE can still be
        in flight when the to-conn's first frame (the pipe-cleaner ping) arrives; polling
        avoids dropping frames on that race."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.from_connections_lock:
                q = self.from_connections.get(client_id)
            if q is not None:
                return q
            time.sleep(0.05)
        return None

    def _handle_from_conn(self, conn, client_id: bytes) -> None:
        q = queue.Queue()
        with self.from_connections_lock:
            self.from_connections[client_id] = q
        logger.info("registered from-conn for client_id=%r", client_id)
        try:
            while not self.stop_event.is_set():
                try:
                    item = q.get(timeout=1.0)
                except queue.Empty:
                    continue
                if item is None:
                    return
                try:
                    write_response(conn, item)
                except OSError:
                    logger.warning("failed to write response on from-conn for %r", client_id)
                    return
        finally:
            with self.from_connections_lock:
                if self.from_connections.get(client_id) is q:
                    del self.from_connections[client_id]
            try:
                conn.close()
            except OSError:
                pass

    def _handle_to_conn(self, conn, client_id: bytes) -> None:
        try:
            while True:
                try:
                    _irm_f0, _client_id, transcode, iso_data = read_request(conn)
                except ConnectionError:
                    return
                self._route_frame(client_id, transcode, iso_data)
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _route_frame(self, client_id: bytes, transcode: bytes, iso_data: bytes) -> None:
        if transcode == PING_TRANSCODE:
            q = self._wait_for_from_conn(client_id)
            if q is not None:
                # Both halves are EBCDIC, including the "PING" marker itself - it must
                # match session.py's skip-check byte-for-byte.
                q.put("PING".encode("cp500") + "PIPES cleaned".encode("cp500"))
            return

        try:
            req, _ = iso8583.decode(iso_data, self.spec)
        except Exception:
            logger.exception("failed to decode request from client_id=%r", client_id)
            return

        self.stats.record_recv()
        mti = req.get("t")

        if mti == "0800":
            resp = dict(req)
            resp["t"] = "0810"
        elif mti == "0120":
            resp = dict(req)
            resp["t"] = "0130"
            resp["39"] = "00"
        elif mti == "0420":
            resp = dict(req)
            resp["t"] = "0430"
            resp["39"] = "00"
        elif mti == "0100":
            resp = self._process_0100(req)
        else:
            logger.warning("unhandled MTI from upstream via router: %s", mti)
            return

        encoded, _ = iso8583.encode(resp, self.spec)

        q = self._wait_for_from_conn(client_id)
        if q is None:
            logger.warning("no from-conn registered for client_id=%r; dropping response", client_id)
            return
        q.put(bytes(encoded))
        self.stats.record_sent()

    def _process_0100(self, req: dict) -> dict:
        pan = req.get("2", "")
        f47 = f47_decode(req.get("47", ""))

        if pan not in self.pans:
            rc = "01"
        elif f47.get("response_code", "00") != "00":
            rc = "01"
        else:
            rc = "00"

        resp = dict(req)
        resp["t"] = "0110"
        resp["39"] = rc
        if rc == "00":
            resp["38"] = self._next_auth_code()

        # Every response must echo f47 back: crypto_host's ARPC step only runs on
        # validate_0110, and the original f55 cryptogram/ATC can only reach that call by
        # round-tripping the request's f47 into the response. Skipping this means ARPC
        # silently never gets computed.
        f47["message_type"] = "0110"
        f47["response_code"] = rc
        resp["47"] = f47_encode(f47)
        return resp

    def _dispatch_new_conn(self, conn) -> None:
        """Reads the first frame off-acceptor, in a fresh thread. The to-conn's first frame
        isn't sent until after the from-conn's resume-TPIPE, but the acceptor must accept
        both TCP connections before blocking on either read - reading here (not in the
        acceptor thread) avoids that deadlock."""
        try:
            irm_f0, client_id, transcode, iso_data = read_request(conn)
        except ConnectionError:
            try:
                conn.close()
            except OSError:
                pass
            return

        if irm_f0 == 0x80:
            self._handle_from_conn(conn, client_id)
        else:
            if transcode:
                self._route_frame(client_id, transcode, iso_data)
            self._handle_to_conn(conn, client_id)

    def _accept_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                conn, _addr = self._listen_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._dispatch_new_conn, args=(conn,), daemon=True).start()

    def start(self) -> None:
        self.cmd.start()
        self._listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listen_sock.bind(("0.0.0.0", self.cfg["port"]))
        self._listen_sock.listen(5)
        self._listen_sock.settimeout(1.0)
        logger.info("downstream host listening on port %d", self.cfg["port"])
        threading.Thread(target=self._accept_loop, daemon=True).start()

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
    sim = DownstreamHostSim(cfg)
    sim.run_forever()

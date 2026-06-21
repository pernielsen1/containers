import argparse
import json
import logging
import os
import queue
import socket
import sys
import threading
import time
from itertools import count

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import iso8583

from shared.command_server import CommandServer
from shared.ims_connect import PING_TRANSCODE, read_request, write_response
from shared.iso_utils import f47_decode, f47_encode, load_spec
from shared.stats import Stats

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


class DownstreamHost:
    """Simulates an IMS Connect authorization host."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.spec = load_spec(cfg["iso_spec"])
        with open(cfg["pans_defined"]) as f:
            self.pans = json.load(f)

        self.stats = Stats(yellow_threshold_seconds=cfg.get("yellow_threshold_seconds"))
        self.stop_event = threading.Event()

        self.from_connections = {}
        self.from_lock = threading.Lock()
        self._auth_code_counter = count(1)
        self._auth_code_lock = threading.Lock()

        self.cmd = CommandServer(cfg["command_port"], self.stats, self.stop_event)
        self._listen_sock = None

    def _next_auth_code(self) -> str:
        with self._auth_code_lock:
            n = next(self._auth_code_counter)
        return str(n).zfill(6)

    def _decline(self, stan: str, pan: str, f47_data: dict, rc: str) -> dict:
        return self._respond(stan, pan, f47_data, rc)

    def _respond(self, stan: str, pan: str, f47_data: dict, rc: str, auth_code: str = None) -> dict:
        # Echo the request's f47 back (with message_type/response_code updated to match
        # this response) so crypto_host's validate_0110 call still has the original f55
        # cryptogram/atc available to compute ARPC — downstream_host never generates that
        # data itself.
        resp_f47 = dict(f47_data)
        resp_f47["message_type"] = "0110"
        resp_f47["response_code"] = rc
        resp = {"t": "0110", "11": stan, "2": pan, "39": rc, "47": f47_encode(resp_f47)}
        if auth_code is not None:
            resp["38"] = auth_code
        return resp

    def _process_0100(self, req: dict) -> dict:
        pan = req.get("2", "")
        stan = req.get("11", "")
        f47_data = f47_decode(req.get("47", ""))

        if pan not in self.pans:
            return self._decline(stan, pan, f47_data, "01")

        if f47_data.get("response_code", "00") != "00":
            return self._decline(stan, pan, f47_data, "01")

        return self._respond(stan, pan, f47_data, "00", auth_code=self._next_auth_code())

    def _wait_for_from_conn(self, client_id: bytes, timeout: float = 2.0):
        # The to-conn and from-conn are independent TCP connections handled by separate
        # threads; the resume-TPIPE that registers the from-conn's queue can still be
        # in flight when the to-conn's first frame (the pipe-cleaner ping) arrives. Poll
        # briefly for the pairing to complete instead of dropping the frame on a race.
        deadline = time.monotonic() + timeout
        while True:
            with self.from_lock:
                q = self.from_connections.get(client_id)
            if q is not None:
                return q
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.01)

    def _route_frame(self, client_id: bytes, transcode: bytes, iso_data: bytes) -> None:
        q = self._wait_for_from_conn(client_id)
        if q is None:
            logger.warning("no from-conn registered for client_id %r", client_id)
            return

        if transcode == PING_TRANSCODE:
            q.put("PING".encode("cp500") + "PIPES cleaned".encode("cp500"))
            return

        req, _ = iso8583.decode(iso_data, self.spec)
        self.stats.record_recv()
        mti = req.get("t")

        if mti == "0800":
            resp = {"t": "0810", "24": req.get("24", "000")}
        elif mti == "0120":
            resp = {"t": "0130", "11": req.get("11", ""), "39": "00"}
        elif mti == "0420":
            resp = {"t": "0430", "11": req.get("11", ""), "39": "00"}
        elif mti == "0100":
            resp = self._process_0100(req)
        else:
            logger.warning("unhandled downstream MTI: %s", mti)
            return

        encoded, _ = iso8583.encode(resp, self.spec)
        q.put(bytes(encoded))
        self.stats.record_sent()

    def _handle_from_conn(self, conn, client_id: bytes) -> None:
        q = queue.Queue()
        with self.from_lock:
            self.from_connections[client_id] = q
        try:
            while True:
                item = q.get()
                if item is None:
                    break
                write_response(conn, item)
        except OSError:
            pass
        finally:
            with self.from_lock:
                if self.from_connections.get(client_id) is q:
                    del self.from_connections[client_id]
            conn.close()

    def _handle_to_conn(self, conn) -> None:
        try:
            while True:
                try:
                    _irm_f0, client_id, transcode, iso_data = read_request(conn)
                except ConnectionError:
                    break
                self._route_frame(client_id, transcode, iso_data)
        finally:
            conn.close()

    def _dispatch_new_conn(self, conn) -> None:
        # Reading the first frame must happen off the acceptor thread: a to-conn and its
        # sibling from-conn arrive as two separate TCP connections, and the to-conn's first
        # frame isn't sent until after the from-conn's resume-TPIPE — accepting both before
        # blocking on either read avoids a deadlock between the two.
        try:
            irm_f0, client_id, transcode, iso_data = read_request(conn)
        except ConnectionError:
            conn.close()
            return

        if irm_f0 == 0x80:
            self._handle_from_conn(conn, client_id)
        else:
            self._route_frame(client_id, transcode, iso_data)
            self._handle_to_conn(conn)

    def _acceptor(self) -> None:
        self._listen_sock.settimeout(1.0)
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
        self._listen_sock.listen(20)

        threading.Thread(target=self._acceptor, daemon=True).start()

    def run_forever(self) -> None:
        self.start()
        self.stop_event.wait()
        if self._listen_sock is not None:
            self._listen_sock.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    args = parser.parse_args()

    cfg = load_config(args.config)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    host = DownstreamHost(cfg)
    host.run_forever()


if __name__ == "__main__":
    main()

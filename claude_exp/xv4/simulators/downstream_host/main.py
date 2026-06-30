import json
import logging
import os
import queue
import socket
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import iso8583
import iso8583.specs

from shared.command_server import CommandServer
from shared.ims_connect import (
    PING_TRANSCODE,
    build_frame,
    read_request,
    to_ebcdic,
    write_response,
)
from shared.iso_utils import f47_decode, f47_encode, load_spec
from shared.stats import Stats

logger = logging.getLogger(__name__)


class DownstreamHost:
    def __init__(self, cfg, spec, pans):
        self._cfg = cfg
        self._spec = spec
        self._pans = pans
        self._from_connections = {}
        self._from_lock = threading.Lock()
        self._auth_counter = 0
        self._auth_lock = threading.Lock()
        self.stats = Stats(yellow_threshold_seconds=cfg.get("yellow_threshold_seconds"))
        self.stop_event = threading.Event()

    def _next_auth_code(self) -> str:
        with self._auth_lock:
            self._auth_counter = (self._auth_counter + 1) % 1_000_000
            return str(self._auth_counter).zfill(6)

    def _wait_for_from_conn(self, client_id: bytes, timeout=2.0):
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._from_lock:
                if client_id in self._from_connections:
                    return
            threading.Event().wait(0.05)

    def _handle_from_conn(self, conn, client_id: bytes):
        q = queue.Queue()
        with self._from_lock:
            self._from_connections[client_id] = q
        try:
            while not self.stop_event.is_set():
                try:
                    item = q.get(timeout=1.0)
                    if item is None:
                        break
                    write_response(conn, item)
                    self.stats.record_sent()
                except queue.Empty:
                    continue
        except OSError as e:
            logger.warning("from-conn %r write error: %s", client_id, e)
        finally:
            with self._from_lock:
                self._from_connections.pop(client_id, None)
            try:
                conn.close()
            except OSError:
                pass

    def _get_from_queue(self, client_id: bytes):
        with self._from_lock:
            return self._from_connections.get(client_id)

    def _route_frame(self, irm_f0, client_id, transcode, iso_data):
        if transcode == PING_TRANSCODE:
            logger.debug("ping from client_id=%r", client_id)
            # Send EBCDIC PING response
            response_data = "PING".encode("cp500") + "PIPES cleaned".encode("cp500")
            q = self._get_from_queue(client_id)
            if q:
                q.put(response_data)
            return

        if not iso_data:
            return

        try:
            req, _ = iso8583.decode(iso_data, self._spec)
        except Exception as e:
            logger.warning("downstream decode error: %s", e)
            return

        self.stats.record_recv()
        mti = req.get("t")

        if mti == "0800":
            resp = {"t": "0810", "24": req.get("24", "100")}
            encoded, _ = iso8583.encode(resp, self._spec)
        elif mti == "0120":
            resp = dict(req)
            resp["t"] = "0130"
            resp["39"] = "00"
            encoded, _ = iso8583.encode(resp, self._spec)
        elif mti == "0420":
            resp = dict(req)
            resp["t"] = "0430"
            resp["39"] = "00"
            encoded, _ = iso8583.encode(resp, self._spec)
        elif mti == "0100":
            resp, encoded = self._process_0100(req)
        else:
            logger.warning("downstream received unhandled mti=%s", mti)
            return

        q = self._get_from_queue(client_id)
        if q:
            q.put(encoded)
        else:
            logger.warning("no from-conn queue for client_id=%r", client_id)

    def _process_0100(self, req):
        pan = req.get("2", "")
        f47_str = req.get("47", "")
        f47_data = f47_decode(f47_str)

        if pan not in self._pans:
            rc = "01"
        elif f47_data.get("response_code", "00") != "00":
            rc = "01"
        else:
            rc = "00"

        resp = dict(req)
        resp["t"] = "0110"
        resp["39"] = rc
        if rc == "00":
            resp["38"] = self._next_auth_code()

        # Echo f47 back with updated message_type and response_code
        f47_data["message_type"] = "0110"
        f47_data["response_code"] = rc
        resp["47"] = f47_encode(f47_data)

        encoded, _ = iso8583.encode(resp, self._spec)
        return resp, encoded

    def _dispatch_new_conn(self, conn):
        try:
            irm_f0, client_id, transcode, iso_data = read_request(conn)
        except ConnectionError as e:
            logger.warning("read first frame error: %s", e)
            try:
                conn.close()
            except OSError:
                pass
            return

        if irm_f0 == 0x80:
            # from-conn
            t = threading.Thread(
                target=self._handle_from_conn, args=(conn, client_id), daemon=True
            )
            t.start()
        else:
            # to-conn — wait for corresponding from-conn first
            self._wait_for_from_conn(client_id)
            t = threading.Thread(
                target=self._handle_to_conn, args=(conn, client_id, transcode, iso_data), daemon=True
            )
            t.start()

    def _handle_to_conn(self, conn, client_id, first_transcode, first_iso_data):
        # Handle the first frame that was already read in _dispatch_new_conn
        self._route_frame(0x00, client_id, first_transcode, first_iso_data)

        try:
            while not self.stop_event.is_set():
                try:
                    irm_f0, cid, transcode, iso_data = read_request(conn)
                    self._route_frame(irm_f0, cid or client_id, transcode, iso_data)
                except ConnectionError as e:
                    logger.info("to-conn %r disconnected: %s", client_id, e)
                    break
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def serve(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", self._cfg["port"]))
        srv.listen(20)
        srv.settimeout(1.0)
        logger.info("downstream host listening on port %d", self._cfg["port"])

        while not self.stop_event.is_set():
            try:
                conn, addr = srv.accept()
                conn.settimeout(None)
                logger.debug("new connection from %s", addr)
                t = threading.Thread(target=self._dispatch_new_conn, args=(conn,), daemon=True)
                t.start()
            except socket.timeout:
                continue
            except OSError as e:
                if not self.stop_event.is_set():
                    logger.error("accept error: %s", e)
                break

        try:
            srv.close()
        except OSError:
            pass


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    cfg_path = os.path.join(base, "config.json")
    with open(cfg_path) as f:
        cfg = json.load(f)

    spec_path = os.path.normpath(os.path.join(base, cfg["iso_spec"]))
    spec = load_spec(spec_path)

    pans_path = os.path.normpath(os.path.join(base, cfg["pans_defined"]))
    with open(pans_path) as f:
        pans = json.load(f)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    host = DownstreamHost(cfg, spec, pans)

    cmd = CommandServer(
        port=cfg["command_port"],
        stats=host.stats,
        stop_event=host.stop_event,
    )
    cmd.start()

    host.serve()


if __name__ == "__main__":
    main()

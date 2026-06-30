import logging
import socket
import threading
from typing import Optional, Tuple

from shared.framing import read_message, write_message

logger = logging.getLogger(__name__)

UpstreamConn = Tuple[socket.socket, tuple, threading.Lock]


class UpstreamServer:
    def __init__(self, cfg):
        self._cfg = cfg
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("0.0.0.0", cfg.port))
        self._sock.listen(5)
        self._sock.settimeout(1.0)
        logger.info("upstream server listening on port %d", cfg.port)

    def accept(self, stop_event) -> Optional[UpstreamConn]:
        while not stop_event.is_set():
            try:
                conn, addr = self._sock.accept()
                conn.settimeout(None)
                logger.info("upstream connected from %s", addr)
                return conn, addr, threading.Lock()
            except socket.timeout:
                continue
            except OSError as e:
                logger.warning("upstream accept error: %s", e)
                return None
        return None

    def close(self):
        try:
            self._sock.close()
        except OSError:
            pass


class UpstreamClient:
    def __init__(self, cfg):
        self._cfg = cfg

    def connect(self, stop_event) -> Optional[UpstreamConn]:
        while not stop_event.is_set():
            try:
                sock = socket.create_connection(
                    (self._cfg.host, self._cfg.port), timeout=5
                )
                sock.settimeout(None)
                addr = (self._cfg.host, self._cfg.port)
                logger.info("upstream client connected to %s:%d", self._cfg.host, self._cfg.port)
                return sock, addr, threading.Lock()
            except OSError as e:
                logger.warning("upstream client connect failed: %s — retrying in %ds",
                               e, self._cfg.retry_seconds)
                stop_event.wait(self._cfg.retry_seconds)
        return None


def read_upstream(conn, cfg) -> bytes:
    return read_message(conn, cfg.framing.to_dict())


def write_upstream(conn, data: bytes, cfg) -> None:
    write_message(conn, data, cfg.framing.to_dict())

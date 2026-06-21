import socket
import threading
import time
from typing import Optional, Tuple

from shared.framing import read_message, write_message

UpstreamConn = Tuple[socket.socket, tuple, threading.Lock]


class UpstreamServer:
    """Listen on cfg.port. Created once outside the session loop (survives reconnects)."""

    def __init__(self, cfg):
        self.cfg = cfg
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((cfg.host, cfg.port))
        self._sock.listen(5)
        self._sock.settimeout(1.0)

    def accept(self, stop_event) -> Optional[UpstreamConn]:
        while not stop_event.is_set():
            try:
                conn, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return None
            return conn, addr, threading.Lock()
        return None

    def close(self):
        self._sock.close()


class UpstreamClient:
    """Connect out to cfg.host:cfg.port, retrying every cfg.retry_seconds."""

    def __init__(self, cfg):
        self.cfg = cfg

    def connect(self, stop_event) -> Optional[UpstreamConn]:
        # Polls stop_event.is_set() every second rather than calling stop_event.wait()
        # directly, so callers can pass any duck-typed "is_set()"-only event (e.g. a
        # combinator of multiple events) in place of a real threading.Event.
        while not stop_event.is_set():
            try:
                sock = socket.create_connection((self.cfg.host, self.cfg.port), timeout=5)
                return sock, (self.cfg.host, self.cfg.port), threading.Lock()
            except OSError:
                waited = 0.0
                while waited < self.cfg.retry_seconds and not stop_event.is_set():
                    time.sleep(min(1.0, self.cfg.retry_seconds - waited))
                    waited += 1.0
        return None


def read_upstream(conn, cfg) -> bytes:
    return read_message(conn, cfg.framing.to_dict())


def write_upstream(conn, data: bytes, cfg) -> None:
    write_message(conn, data, cfg.framing.to_dict())

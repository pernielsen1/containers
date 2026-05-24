"""UpstreamServer / UpstreamClient — two clean classes, same interface.

C++ equivalent: abstract IUpstreamFactory with ServerFactory and ClientFactory
subclasses; clean virtual dispatch for server vs client mode.
"""
from __future__ import annotations

import logging
import socket
import threading
from typing import Optional, Tuple

from shared.framing import read_message, write_message
from .config import UpstreamConfig

log = logging.getLogger(__name__)

# Type alias for an upstream connection handle
UpstreamConn = Tuple[socket.socket, tuple, threading.Lock]  # (sock, addr, write_lock)


class UpstreamServer:
    """Listens on a port and accepts one upstream connection at a time.

    C++ equivalent: acceptor loop using blocking accept(); one connection active.
    """

    def __init__(self, cfg: UpstreamConfig) -> None:
        self._cfg  = cfg
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("", cfg.port))
        self._sock.listen(10)
        log.info("router: upstream server on :%d", cfg.port)

    def accept(self, stop_event: threading.Event) -> Optional[UpstreamConn]:
        """Block until a connection arrives or stop_event is set. Returns None on stop."""
        while not stop_event.is_set():
            self._sock.settimeout(1)
            try:
                conn, addr = self._sock.accept()
                log.info("router: upstream connected %s", addr)
                return conn, addr, threading.Lock()
            except socket.timeout:
                continue
            except OSError:
                return None
        return None

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


class UpstreamClient:
    """Connects outward to an upstream host, retrying until successful or stopped.

    C++ equivalent: connector loop with retry; same stop_event pattern.
    """

    def __init__(self, cfg: UpstreamConfig) -> None:
        self._cfg = cfg

    def connect(self, stop_event: threading.Event) -> Optional[UpstreamConn]:
        """Block until connected or stop_event is set. Returns None on stop."""
        host  = self._cfg.host
        port  = self._cfg.port
        retry = self._cfg.retry_seconds
        while not stop_event.is_set():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect((host, port))
                log.info("router: connected to upstream %s:%d", host, port)
                return sock, (host, port), threading.Lock()
            except OSError as e:
                log.info("router: upstream %s:%d unavailable (%s), retrying in %ds",
                         host, port, e, retry)
                stop_event.wait(timeout=retry)
        return None


def read_upstream(conn: socket.socket, cfg: UpstreamConfig) -> bytes:
    """Read one framed message from an upstream connection."""
    return read_message(conn, cfg.framing.to_dict())


def write_upstream(conn: socket.socket, data: bytes, cfg: UpstreamConfig) -> None:
    """Write one framed message to an upstream connection."""
    write_message(conn, data, cfg.framing.to_dict())

import logging
import socket
import threading
import time

from shared.framing import read_message, write_message
from shared.ssl_utils import wrap_client_socket, wrap_server_socket

logger = logging.getLogger(__name__)


class UpstreamServer:
    """Listen on cfg.port. Created once outside the session loop (survives reconnects)."""

    def __init__(self, cfg):
        self.cfg = cfg
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((cfg.host, cfg.port))
        self._sock.listen(5)
        self._sock.settimeout(1.0)
        logger.info("upstream server listening on port %d", cfg.port)

    def accept(self, stop_event):
        while not stop_event.is_set():
            try:
                conn, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return None
            if self.cfg.ssl_active:
                try:
                    conn = wrap_server_socket(
                        conn,
                        ssl_active=True,
                        certfile=self.cfg.certfile,
                        keyfile=self.cfg.keyfile,
                        cafile=self.cfg.cafile,
                    )
                except OSError as e:
                    # A single bad handshake (stray probe, client reconnecting too fast, ...)
                    # must not kill this accept loop - that would permanently strand the router
                    # with no way to ever accept an upstream connection again.
                    logger.warning("upstream handshake failed from %s: %s", addr, e)
                    conn.close()
                    continue
            conn.settimeout(None)
            logger.info("upstream connected from %s", addr)
            return conn, addr, threading.Lock()
        return None

    def close(self):
        try:
            self._sock.close()
        except OSError:
            pass


class UpstreamClient:
    """Connect out to cfg.host:cfg.port, retrying every cfg.retry_seconds."""

    def __init__(self, cfg):
        self.cfg = cfg

    def connect(self, stop_event):
        while not stop_event.is_set():
            try:
                sock = socket.create_connection((self.cfg.host, self.cfg.port), timeout=5)
                sock = wrap_client_socket(
                    sock,
                    ssl_active=self.cfg.ssl_active,
                    certfile=self.cfg.certfile,
                    keyfile=self.cfg.keyfile,
                    cafile=self.cfg.cafile,
                    server_hostname=self.cfg.host,
                )
                sock.settimeout(None)  # switch to blocking; timeout=5 above is connect-only
            except OSError:
                elapsed = 0.0
                while elapsed < self.cfg.retry_seconds:
                    if stop_event.is_set():
                        return None
                    time.sleep(min(1.0, self.cfg.retry_seconds - elapsed))
                    elapsed += 1.0
                continue
            addr = sock.getpeername()
            logger.info("connected to upstream at %s", addr)
            return sock, addr, threading.Lock()
        return None


def read_upstream(conn, cfg) -> bytes:
    return read_message(conn, cfg.framing.to_dict())


def write_upstream(conn, data: bytes, cfg) -> None:
    write_message(conn, data, cfg.framing.to_dict())

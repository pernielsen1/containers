import logging
import socket
import ssl
import threading
import time

from shared.framing import read_message, write_message
from shared.ssl_utils import is_cert_desync_error, wrap_client_socket, wrap_server_socket

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
                except ssl.SSLError as e:
                    conn.close()
                    if is_cert_desync_error(e):
                        # Unlike a stray probe or a client reconnecting too fast, this means
                        # the certs on the two sides are actually out of sync - it will keep
                        # failing on every attempt from this peer until a human fixes it. ERROR
                        # (not WARNING) flags that distinction - see is_cert_desync_error() for
                        # why the other SSLError cases (e.g. a peer dropping the TCP connection
                        # mid-handshake) must NOT hit this path; the accept loop itself still
                        # continues below either way so the router stays ready for the next
                        # connection attempt.
                        logger.error(
                            "TLS handshake failed accepting upstream connection from %s - "
                            "certificates may be out of sync and this cannot self-recover, "
                            "needs manual intervention: %s", addr, e,
                        )
                    else:
                        logger.warning("upstream handshake failed from %s: %s", addr, e)
                    continue
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

    def _retry_wait(self, stop_event) -> bool:
        """Sleep up to cfg.retry_seconds, checking stop_event. Returns False if stop requested."""
        elapsed = 0.0
        while elapsed < self.cfg.retry_seconds:
            if stop_event.is_set():
                return False
            time.sleep(min(1.0, self.cfg.retry_seconds - elapsed))
            elapsed += 1.0
        return True

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
            except ssl.SSLError as e:
                sock.close()
                if is_cert_desync_error(e):
                    # Same "can't self-heal by retrying" distinction as the downstream/
                    # server-mode sites - the certs are actually out of sync, not just a peer
                    # that isn't up yet or a handshake that got cut short mid-reconnect (see
                    # is_cert_desync_error()).
                    logger.error(
                        "TLS handshake failed connecting to upstream %s:%d - certificates may "
                        "be out of sync and this cannot self-recover, needs manual "
                        "intervention: %s", self.cfg.host, self.cfg.port, e,
                    )
                else:
                    logger.warning(
                        "TLS handshake failed connecting to upstream %s:%d: %s",
                        self.cfg.host, self.cfg.port, e,
                    )
                if not self._retry_wait(stop_event):
                    return None
                continue
            except OSError:
                if not self._retry_wait(stop_event):
                    return None
                continue
            addr = sock.getpeername()
            logger.info("connected to upstream at %s", addr)
            return sock, addr, threading.Lock()
        return None


def read_upstream(conn, cfg) -> bytes:
    return read_message(conn, cfg.framing.to_dict())


def write_upstream(conn, data: bytes, cfg) -> None:
    write_message(conn, data, cfg.framing.to_dict())

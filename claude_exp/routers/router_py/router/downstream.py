import logging
import socket
import threading

from shared.ims_connect import PING_TRANSCODE, build_frame, read_response
from shared.ssl_utils import wrap_client_socket

logger = logging.getLogger(__name__)


class DownstreamConnection:
    """Dual-socket IMS session. Thread-safe send via internal Lock."""

    def __init__(self, to_sock, from_sock):
        self._to_sock = to_sock
        self._from_sock = from_sock
        self._lock = threading.Lock()

    @classmethod
    def connect(cls, cfg) -> "DownstreamConnection":
        to_sock = socket.create_connection((cfg.host, cfg.port))
        from_sock = socket.create_connection((cfg.host, cfg.port))
        to_sock = wrap_client_socket(
            to_sock,
            ssl_active=cfg.ssl_active,
            certfile=cfg.certfile,
            keyfile=cfg.keyfile,
            cafile=cfg.cafile,
            server_hostname=cfg.host,
        )
        from_sock = wrap_client_socket(
            from_sock,
            ssl_active=cfg.ssl_active,
            certfile=cfg.certfile,
            keyfile=cfg.keyfile,
            cafile=cfg.cafile,
            server_hostname=cfg.host,
        )

        resume_frame = build_frame(0x80, cfg.irm_id, cfg.client_id)
        from_sock.sendall(resume_frame)

        ping_data = "1234 clean the pipes".encode("cp500")
        ping_frame = build_frame(0x00, cfg.irm_id, cfg.client_id, transcode=PING_TRANSCODE, data=ping_data)
        to_sock.sendall(ping_frame)

        logger.info("downstream connected to %s:%d", cfg.host, cfg.port)
        return cls(to_sock, from_sock)

    def send(self, frame: bytes) -> None:
        with self._lock:
            self._to_sock.sendall(frame)

    def recv(self) -> bytes:
        return read_response(self._from_sock)

    def close(self) -> None:
        # shutdown() before close() matters here: recv() (see above) runs on a separate
        # ds-receiver thread and can be blocked in it at the exact moment teardown calls close().
        # A bare close() releases the fd number immediately, racing a blocked recv() on that same
        # fd against the kernel handing the number to a brand-new socket (e.g. this same session's
        # own reconnect, or an unrelated connection) before the blocked syscall notices - the
        # observed symptom was "Bad file descriptor" appearing right after a fresh "downstream
        # connected" log line. shutdown(SHUT_RDWR) forces any in-progress blocking recv() on this
        # exact socket to return immediately with a clean error tied to *this* connection, before
        # the fd is released for reuse.
        for sock in (self._to_sock, self._from_sock):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        for sock in (self._to_sock, self._from_sock):
            try:
                sock.close()
            except OSError:
                pass

import logging
import socket
import threading

from shared.ims_connect import PING_TRANSCODE, build_frame, read_response

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
        for sock in (self._to_sock, self._from_sock):
            try:
                sock.close()
            except OSError:
                pass

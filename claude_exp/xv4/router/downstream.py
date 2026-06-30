import logging
import socket
import threading

from shared.ims_connect import (
    build_frame,
    read_response,
    PING_TRANSCODE,
)

logger = logging.getLogger(__name__)


class DownstreamConnection:
    def __init__(self, to_sock, from_sock, cfg):
        self._to_sock = to_sock
        self._from_sock = from_sock
        self._cfg = cfg
        self._lock = threading.Lock()

    @classmethod
    def connect(cls, cfg) -> "DownstreamConnection":
        to_sock = socket.create_connection((cfg.host, cfg.port), timeout=5)
        to_sock.settimeout(None)
        from_sock = socket.create_connection((cfg.host, cfg.port), timeout=5)
        from_sock.settimeout(None)

        # Resume TPIPE on from_sock
        resume = build_frame(0x80, cfg.irm_id, cfg.client_id)
        from_sock.sendall(resume)

        # Pipe-cleaner ping on to_sock
        ping_data = "1234 clean the pipes".encode("cp500")
        ping = build_frame(
            0x00, cfg.irm_id, cfg.client_id,
            transcode=PING_TRANSCODE, data=ping_data
        )
        to_sock.sendall(ping)

        logger.info("downstream connected to %s:%d", cfg.host, cfg.port)
        return cls(to_sock, from_sock, cfg)

    def send(self, frame: bytes) -> None:
        with self._lock:
            self._to_sock.sendall(frame)

    def recv(self) -> bytes:
        return read_response(self._from_sock)

    def close(self) -> None:
        for s in (self._to_sock, self._from_sock):
            try:
                s.close()
            except OSError:
                pass

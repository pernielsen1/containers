"""DownstreamConnection — IMS-connect socket pair with write lock.

C++ equivalent: RAII class owning two file descriptors + std::mutex.
Destructor closes both sockets; send() acquires unique_lock.
"""
from __future__ import annotations

import logging
import socket
import threading

from shared import ims_connect
from .config import DownstreamConfig

log = logging.getLogger(__name__)


class DownstreamConnection:
    """One connected IMS session: a to-socket (send requests) and a
    from-socket (receive responses). Thread-safe send via internal lock."""

    def __init__(self, to_sock: socket.socket, from_sock: socket.socket) -> None:
        self._to   = to_sock
        self._from = from_sock
        self._lock = threading.Lock()

    # ── factory ───────────────────────────────────────────────────────────────

    @classmethod
    def connect(cls, cfg: DownstreamConfig) -> DownstreamConnection:
        """Connect both sockets and perform the IMS handshake.

        Raises OSError if the host is unreachable.
        C++ equivalent: static factory returning unique_ptr<DownstreamConnection>.
        """
        to_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        to_sock.connect((cfg.host, cfg.port))
        log.info("router: connected to downstream port=%d (to)", cfg.port)

        from_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        from_sock.connect((cfg.host, cfg.port))
        log.info("router: connected to downstream port=%d (from)", cfg.port)

        # IMS handshake: resume TPIPE then pipe-cleaner ping
        resume = ims_connect.build_frame(0x80, cfg.irm_id, cfg.client_id)
        from_sock.sendall(resume)
        log.info("router: sent resume TPIPE")

        ping_data  = "1234 clean the pipes".encode("cp500")
        ping_frame = ims_connect.build_frame(
            0x00, cfg.irm_id, cfg.client_id,
            transcode=ims_connect.PING_TRANSCODE, data=ping_data,
        )
        to_sock.sendall(ping_frame)
        log.info("router: sent pipe-cleaner ping")

        return cls(to_sock, from_sock)

    # ── I/O ───────────────────────────────────────────────────────────────────

    def send(self, frame: bytes) -> None:
        """Thread-safe send on the to-socket. OSError propagates to caller."""
        with self._lock:
            self._to.sendall(frame)

    def recv(self) -> bytes:
        """Blocking read from the from-socket. Raises ConnectionError on close."""
        return ims_connect.read_response(self._from)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        for sock in (self._to, self._from):
            try:
                sock.close()
            except OSError:
                pass

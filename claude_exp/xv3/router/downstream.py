import socket
import threading

from shared.ims_connect import PING_TRANSCODE, build_frame, read_response


class DownstreamConnection:
    """Dual-socket IMS session. Thread-safe send via internal Lock."""

    def __init__(self, to_sock, from_sock, cfg):
        self.to_sock = to_sock
        self.from_sock = from_sock
        self.cfg = cfg
        self._lock = threading.Lock()

    @classmethod
    def connect(cls, cfg) -> "DownstreamConnection":
        to_sock = None
        from_sock = None
        try:
            to_sock = socket.create_connection((cfg.host, cfg.port))
            from_sock = socket.create_connection((cfg.host, cfg.port))

            from_sock.sendall(build_frame(0x80, cfg.irm_id, cfg.client_id))

            ping_data = "1234 clean the pipes".encode("cp500")
            to_sock.sendall(
                build_frame(0x00, cfg.irm_id, cfg.client_id, transcode=PING_TRANSCODE, data=ping_data)
            )

            return cls(to_sock, from_sock, cfg)
        except OSError:
            # No process exits without releasing its sockets — close whatever connected
            # before re-raising for the caller's reconnect loop.
            if to_sock is not None:
                to_sock.close()
            if from_sock is not None:
                from_sock.close()
            raise

    def send(self, frame: bytes) -> None:
        with self._lock:
            self.to_sock.sendall(frame)

    def recv(self) -> bytes:
        return read_response(self.from_sock)

    def close(self) -> None:
        for sock in (self.to_sock, self.from_sock):
            try:
                sock.close()
            except OSError:
                pass

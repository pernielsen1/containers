"""Minimal, fully test-controlled stand-in for the router - lets a test drive UpstreamHostSim
(or any client speaking the same wire protocol) in isolation, without spinning up the real
crypto_host/downstream_host/router stack. Useful whenever a test cares about upstream_host's own
protocol-level behavior (timeouts, retries, advice/reversal messages, ...) rather than full-stack
integration - see test_advice_reversal.py for the pattern this was built for.

Unlike the real router, this never touches crypto_host or downstream_host: it answers directly
per a per-MTI reply_policy the test controls (default: always ack). Every inbound message is also
recorded in `received` so a test can assert on exactly what showed up, in what order."""
import socket
import threading

import iso8583

from upstream_shared.framing import read_message, write_message

_ADVICE_ACK = {"0420": "0430", "0120": "0130"}


class StubRouter:
    def __init__(self, spec, framing: dict, port: int = 0):
        self.spec = spec
        self.framing = framing
        self.port = port
        self._sock = None
        self.conn = None
        self.received = []
        # mti -> bool. True (default) acks it with the standard echo-with-changed-mti pattern
        # this repo's real downstream_host/router already use for 0100/0420/0120; set to False
        # to black-hole that MTI (never reply) for a specific test.
        self.reply_policy = {}
        self._lock = threading.Lock()
        self._accept_thread = None

    def start(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", self.port))
        self.port = self._sock.getsockname()[1]
        self._sock.listen(1)
        self._accept_thread = threading.Thread(target=self._accept, daemon=True)
        self._accept_thread.start()

    def stop(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        if self.conn is not None:
            try:
                self.conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.conn.close()
            except OSError:
                pass

    def _accept(self) -> None:
        try:
            conn, _ = self._sock.accept()
        except OSError:
            return
        self.conn = conn
        while True:
            try:
                data = read_message(conn, self.framing)
            except ConnectionError:
                return
            req, _ = iso8583.decode(data, self.spec)
            with self._lock:
                self.received.append(req)
            self._maybe_reply(conn, req)

    def _maybe_reply(self, conn, req: dict) -> None:
        mti = req.get("t")
        if mti == "0100":
            if self.reply_policy.get("0100", True):
                resp = dict(req)
                resp["t"] = "0110"
                resp["39"] = "00"
                write_message(conn, bytes(iso8583.encode(resp, self.spec)[0]), self.framing)
        elif mti in _ADVICE_ACK:
            if self.reply_policy.get(mti, True):
                resp = dict(req)
                resp["t"] = _ADVICE_ACK[mti]
                write_message(conn, bytes(iso8583.encode(resp, self.spec)[0]), self.framing)

    def received_mtis_for(self, pan: str) -> list:
        with self._lock:
            return [r.get("t") for r in self.received if r.get("2") == pan]

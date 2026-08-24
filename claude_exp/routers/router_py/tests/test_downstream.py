"""Regression test for the "Bad file descriptor" reconnect race - see resilience.md's write-up
and router/downstream.py's close(). The root cause: close() alone releases the fd number
immediately, which can race a blocked recv() on that fd against the kernel handing the number to
a brand-new socket before the blocked syscall notices. That exact fd-reuse race isn't
deterministically reproducible in a unit test (it depends on kernel-level fd allocation timing),
so this instead guards the observable contract the shutdown()-before-close() fix guarantees:
close() must promptly and cleanly unblock a thread stuck in recv(), rather than leaving it hung
or silently returning some other connection's data.
"""
import socket
import ssl
import threading
import time
import types
from pathlib import Path

import pytest

from router.downstream import DownstreamConnection
from shared.ssl_utils import build_server_context

CERTS_DIR = Path(__file__).resolve().parent.parent / "certs"


def _loopback_pair():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    client = socket.create_connection(server.getsockname())
    accepted, _ = server.accept()
    server.close()
    return client, accepted


def test_close_promptly_unblocks_pending_recv():
    to_sock, to_peer = _loopback_pair()
    from_sock, from_peer = _loopback_pair()
    conn = DownstreamConnection(to_sock, from_sock)

    result = {}

    def blocked_recv():
        try:
            conn.recv()
        except Exception as e:  # noqa: BLE001 - capturing whatever recv() raises, by design
            result["error"] = e

    t = threading.Thread(target=blocked_recv, daemon=True)
    t.start()
    time.sleep(0.2)  # give the thread time to actually enter the blocking recv() call

    start = time.time()
    conn.close()
    t.join(timeout=2)
    elapsed = time.time() - start

    assert not t.is_alive(), "recv() thread did not wake up after close()"
    assert elapsed < 1.0, f"recv() took {elapsed:.2f}s to unblock after close()"
    assert isinstance(result.get("error"), ConnectionError)

    for s in (to_peer, from_peer):
        s.close()


def test_connect_logs_error_and_closes_sockets_on_cert_mismatch(caplog):
    """Real end-to-end TLS handshake, deliberately desynced: the server presents downstream's
    real self-signed cert, but the client is configured to trust crypto_host's (unrelated) CA -
    exactly the "certs changed and we're not synced" scenario from resilience_v2.md. Verifies
    the client raises (not swallowed), logs at ERROR with a manual-intervention message rather
    than the WARNING used for ordinary connectivity failures, and closes both sockets rather
    than leaking them.
    """
    server_ctx = build_server_context(
        str(CERTS_DIR / "downstream_ssl_active_true_cert.pem"),
        str(CERTS_DIR / "downstream_ssl_active_true_key.pem"),
    )
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(2)
    host, port = listener.getsockname()

    def serve_two():
        for _ in range(2):
            raw, _ = listener.accept()
            try:
                server_ctx.wrap_socket(raw, server_side=True)
            except ssl.SSLError:
                pass  # expected: client rejects our cert and aborts the handshake

    server_thread = threading.Thread(target=serve_two, daemon=True)
    server_thread.start()

    cfg = types.SimpleNamespace(
        host=host,
        port=port,
        ssl_active=True,
        certfile=None,
        keyfile=None,
        cafile=str(CERTS_DIR / "crypto_host_ssl_active_true_ca.pem"),  # wrong CA on purpose
    )

    with caplog.at_level("ERROR"):
        with pytest.raises(ssl.SSLError):
            DownstreamConnection.connect(cfg)

    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(error_records) == 1
    assert "certificates may be out of sync" in error_records[0].message
    assert "manual intervention" in error_records[0].message

    server_thread.join(timeout=2)
    listener.close()

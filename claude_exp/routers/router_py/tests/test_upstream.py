"""Cert-desync ERROR logging for the upstream leg (both server-mode accept and client-mode
connect) - the resilience_v2.md scenario: certs on the two sides have drifted out of sync, which
can't self-heal by retrying and needs to be logged distinctly from ordinary connectivity
failures. Mirrors test_downstream.py's equivalent coverage for the downstream leg.
"""
import socket
import ssl
import threading
import time
import types
from pathlib import Path

from router.upstream import UpstreamClient, UpstreamServer
from shared.ssl_utils import build_client_context, build_server_context

CERTS_DIR = Path(__file__).resolve().parent.parent / "certs"


def test_server_accept_logs_error_on_cert_mismatch(caplog):
    """A client with a mismatched cafile connects in to a real UpstreamServer - the server-side
    handshake fails, and accept() must log ERROR (not the WARNING used for a stray/non-TLS
    probe) rather than silently continuing to look like ordinary noise."""
    cfg = types.SimpleNamespace(
        host="127.0.0.1",
        port=0,
        ssl_active=True,
        certfile=str(CERTS_DIR / "upstream_router_1_ssl_active_true_cert.pem"),
        keyfile=str(CERTS_DIR / "upstream_router_1_ssl_active_true_key.pem"),
        cafile=None,
    )
    server = UpstreamServer(cfg)
    host, port = server._sock.getsockname()

    stop_event = threading.Event()
    accept_result = {}

    def run_accept():
        accept_result["value"] = server.accept(stop_event)

    accept_thread = threading.Thread(target=run_accept, daemon=True)
    accept_thread.start()

    raw = socket.create_connection((host, port))
    client_ctx = build_client_context(
        cafile=str(CERTS_DIR / "crypto_host_ssl_active_true_ca.pem")  # wrong CA on purpose
    )
    try:
        client_ctx.wrap_socket(raw, server_hostname=host)
    except ssl.SSLError:
        pass  # expected: client rejects the server's real cert
    finally:
        raw.close()

    time.sleep(0.2)  # let the server-side handshake attempt finish and log before we stop it
    stop_event.set()
    accept_thread.join(timeout=3)
    server.close()

    assert not accept_thread.is_alive()
    assert accept_result["value"] is None

    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(error_records) == 1
    assert "certificates may be out of sync" in error_records[0].message
    assert "manual intervention" in error_records[0].message


def test_client_connect_logs_error_and_stops_on_cert_mismatch(caplog):
    """A real UpstreamClient connecting out to a server presenting a cert it doesn't trust must
    raise on the client's own wrap_client_socket call, log ERROR (not stay completely silent,
    which is what this path did before), and still respect stop_event rather than wedging."""
    server_ctx = build_server_context(
        str(CERTS_DIR / "upstream_router_2_ssl_active_true_cert.pem"),
        str(CERTS_DIR / "upstream_router_2_ssl_active_true_key.pem"),
    )
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    host, port = listener.getsockname()

    stop_event = threading.Event()

    def serve_one_then_stop():
        raw, _ = listener.accept()
        try:
            server_ctx.wrap_socket(raw, server_side=True)
        except ssl.SSLError:
            pass  # expected: client rejects our cert and aborts the handshake
        finally:
            stop_event.set()  # end the client's retry loop right after this one attempt

    server_thread = threading.Thread(target=serve_one_then_stop, daemon=True)
    server_thread.start()

    cfg = types.SimpleNamespace(
        host=host,
        port=port,
        ssl_active=True,
        certfile=None,
        keyfile=None,
        cafile=str(CERTS_DIR / "crypto_host_ssl_active_true_ca.pem"),  # wrong CA on purpose
        retry_seconds=5,
    )

    result = UpstreamClient(cfg).connect(stop_event)
    server_thread.join(timeout=3)
    listener.close()

    assert result is None

    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(error_records) == 1
    assert "certificates may be out of sync" in error_records[0].message
    assert "manual intervention" in error_records[0].message

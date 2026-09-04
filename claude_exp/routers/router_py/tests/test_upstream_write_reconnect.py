"""A write failure on the upstream<->router link must trigger reconnection on its own, not just
wait for _receive_loop's read side to eventually notice (or never, on a half-open/blackholed
socket - see soak_resilience_hard.py's real-crypto findings: a before_kill stage that came back
entirely 0 sent/0 received after a host restart left a stale-but-flagged-connected link behind).
_write_frame is the single shared write path (_send_loop/_keepalive_loop/advice loops all go
through it) - these tests exercise it directly, same pattern test_crypto_breaker.py uses for the
analogous crypto-client generation/idle-timeout checks.
"""
import socket
import time

# Import order matters: upstream_host.main (pulled in transitively here) inserts its own
# directory onto sys.path as a side effect, which is what makes the bare `upstream_shared` import
# below resolve at all - see conftest.py's own comment on this package layout.
from tests.test_advice_reversal import stub_and_upstream  # noqa: F401  (shared fixture)

from upstream_shared.iso_utils import build_0800


def test_write_failure_sets_disc_evt_and_clears_connection(stub_and_upstream):
    up, router, _cfg = stub_and_upstream
    conn = up._get_conn()
    disc_evt = conn.disc_evt
    assert disc_evt is not None and not disc_evt.is_set()

    # Simulate a dead peer without upstream_host having any way to know yet (no read/write since
    # the peer vanished) - exactly the class of staleness a keepalive-only idle gap or a host
    # restart can leave behind.
    router.conn.shutdown(socket.SHUT_RDWR)
    router.conn.close()

    # TCP quirk: the first write after a peer close/RST often still succeeds locally (it lands in
    # the send buffer before the RST arrives) - only a write after the RST has actually been
    # processed reliably fails. A short bounded retry loop is the real-world equivalent of what
    # _keepalive_loop/_send_loop naturally do (repeated writes over time), not a workaround for
    # something wrong with _write_frame itself.
    deadline = time.time() + 2
    ok = True
    while ok and time.time() < deadline:
        ok = up._write_frame(conn, build_0800(up.spec))
        if ok:
            time.sleep(0.05)
    assert not ok, "a write against a closed peer must eventually fail"
    assert disc_evt.is_set(), "a genuine write failure must set the active connection's disc_evt"

    deadline = time.time() + 2
    while up._get_conn() is not None and time.time() < deadline:
        time.sleep(0.02)
    assert up._get_conn() is None, "disc_evt firing must tear the stale connection down"
    assert up.stats._connections.get("router") is False


def test_probe_connection_reports_false_after_write_failure(stub_and_upstream):
    up, router, _cfg = stub_and_upstream
    conn = up._get_conn()

    router.conn.shutdown(socket.SHUT_RDWR)
    router.conn.close()
    deadline = time.time() + 2
    ok = True
    while ok and time.time() < deadline:
        ok = up._write_frame(conn, build_0800(up.spec))
        if ok:
            time.sleep(0.05)
    assert not ok, "a write against a closed peer must eventually fail"

    deadline = time.time() + 2
    while up._get_conn() is not None and time.time() < deadline:
        time.sleep(0.02)
    assert up._get_conn() is None, "disc_evt firing must tear the stale connection down"

    # /probe_connection is the wrapper wait_for_ready calls - conn is already None post-teardown,
    # so this exercises its "not connected at all" branch specifically.
    with up.cmd.app.test_client() as client:
        resp = client.get("/probe_connection")
    assert resp.status_code == 200
    assert resp.get_json() == {"connected": False}

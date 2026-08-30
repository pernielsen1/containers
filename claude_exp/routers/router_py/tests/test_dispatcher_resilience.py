import logging
import os
import socket
import threading
import time

import iso8583
import pytest

from router.config import CryptoConfig, DownstreamConfig, Framing, RouterConfig, UpstreamConfig
from router.dispatcher import Dispatcher, PendingEntry, RoutedMessage
from shared.framing import read_message
from shared.ims_connect import to_ebcdic
from shared.iso_utils import load_spec
from shared.stats import Stats

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC_PATH = os.path.join(PROJECT_ROOT, "test_spec.json")
SPEC = load_spec(SPEC_PATH)


class FakeDownstream:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send(self, frame):
        if self.fail:
            raise OSError("simulated downstream failure")
        self.sent.append(frame)


class FakeCrypto:
    def validate(self, endpoint, pan, f47, router_stan=""):
        return ""


class RecordingCrypto:
    def __init__(self):
        self.calls = []

    def validate(self, endpoint, pan, f47, router_stan=""):
        self.calls.append(endpoint)
        return ""


class FailingCrypto:
    """Models a genuine crypto_host failure (breaker open or HTTP error) - real CryptoClient
    returns None here, distinct from FakeCrypto's "" (a no-op success, still forwarded) - see
    CryptoClient.validate's docstring."""

    def validate(self, endpoint, pan, f47, router_stan=""):
        return None


def _make_cfg(**overrides):
    framing = Framing(header_hex="", length_field_type="ASCII", length_field_bytes=4)
    upstream = UpstreamConfig(port=15000, framing=framing)
    downstream = DownstreamConfig(
        host="localhost", port=15001, irm_id=to_ebcdic("IRM0001", 8), client_id=to_ebcdic("CLIENT01", 8)
    )
    crypto = CryptoConfig(host="localhost", port=15002, plugin_id="test-plugin", bearer_token="test-token")
    kwargs = dict(
        name="test_router",
        command_port=19100,
        upstream=upstream,
        downstream=downstream,
        crypto=crypto,
        iso_spec=SPEC_PATH,
        queue_maxsize=3,
        pending_ttl_seconds=1,
        worker_threads=1,
    )
    kwargs.update(overrides)
    return RouterConfig(**kwargs)


def _make_dispatcher(**overrides):
    cfg = _make_cfg(**overrides)
    stats = Stats()
    downstream = FakeDownstream()
    crypto = FakeCrypto()
    reconnect_event = threading.Event()
    dispatcher = Dispatcher(cfg, downstream, crypto, SPEC, stats, reconnect_event)
    return dispatcher, cfg, downstream, stats


def test_response_leg_uses_crypto_response_client_when_given():
    """router/session.py wires a separate, shorter-timeout CryptoClient for validate_0110 -
    see briefs/resilience_v2.md's "fire and forget" round. Confirms the routing, not the
    timeout itself (that's crypto_client.py's own concern)."""
    cfg = _make_cfg(pending_ttl_seconds=100)
    stats = Stats()
    downstream = FakeDownstream()
    request_crypto = RecordingCrypto()
    response_crypto = RecordingCrypto()
    reconnect_event = threading.Event()
    dispatcher = Dispatcher(
        cfg, downstream, request_crypto, SPEC, stats, reconnect_event,
        crypto_response=response_crypto,
    )

    up_conn, test_conn = socket.socketpair()
    write_lock = threading.Lock()
    try:
        req = {"t": "0100", "2": "4111111111111111", "3": "000000", "4": "000000000100", "11": "000042"}
        msg = RoutedMessage(req=req, up_conn=up_conn, up_write_lock=write_lock, up_addr=("x", 0))
        dispatcher._process(msg)
        assert request_crypto.calls == ["validate_0100"]
        assert response_crypto.calls == []

        router_stan = next(iter(dispatcher._pending))
        resp = {"t": "0110", "11": router_stan, "39": "00"}
        dispatcher.handle_response(resp)
        assert request_crypto.calls == ["validate_0100"]
        assert response_crypto.calls == ["validate_0110"]
    finally:
        up_conn.close()
        test_conn.close()


def test_dispatcher_defaults_crypto_response_to_crypto_when_omitted():
    """Backward-compat default (matches every other _make_dispatcher() call in this file, which
    doesn't pass crypto_response) - both legs land on the same client when only one is given."""
    dispatcher, cfg, downstream, stats = _make_dispatcher(pending_ttl_seconds=100)
    assert dispatcher.crypto_response is dispatcher.crypto


def test_response_leg_crypto_failure_drops_response_instead_of_forwarding():
    """briefs/resilience_v2.md's crypto-kill scenario: crypto_host succeeds on the request leg
    but fails on the response leg, so upstream never gets its 0110 and falls back to its own
    advice_timeout_seconds -> 0420/0120. A genuine validate_0110 failure (None, not FakeCrypto's
    "" no-op) must drop the response rather than forward it unvalidated."""
    cfg = _make_cfg(pending_ttl_seconds=100)
    stats = Stats()
    downstream = FakeDownstream()
    request_crypto = RecordingCrypto()
    response_crypto = FailingCrypto()
    reconnect_event = threading.Event()
    dispatcher = Dispatcher(
        cfg, downstream, request_crypto, SPEC, stats, reconnect_event,
        crypto_response=response_crypto,
    )

    up_conn, test_conn = socket.socketpair()
    write_lock = threading.Lock()
    try:
        req = {"t": "0100", "2": "4111111111111111", "3": "000000", "4": "000000000100", "11": "000042"}
        msg = RoutedMessage(req=req, up_conn=up_conn, up_write_lock=write_lock, up_addr=("x", 0))
        dispatcher._process(msg)
        assert request_crypto.calls == ["validate_0100"]

        router_stan = next(iter(dispatcher._pending))
        resp = {"t": "0110", "11": router_stan, "39": "00"}
        dispatcher.handle_response(resp)

        test_conn.settimeout(0.2)
        with pytest.raises(socket.timeout):
            test_conn.recv(4096)
    finally:
        up_conn.close()
        test_conn.close()


def test_pending_entry_ttl_expiry_sends_local_decline():
    dispatcher, cfg, downstream, stats = _make_dispatcher(pending_ttl_seconds=1)
    dispatcher.start()

    up_conn, test_conn = socket.socketpair()
    write_lock = threading.Lock()
    try:
        req = {"t": "0100", "2": "4111111111111111", "3": "000000", "4": "000000000100", "11": "000001"}
        dispatcher.submit(RoutedMessage(req=req, up_conn=up_conn, up_write_lock=write_lock, up_addr=("x", 0)))

        time.sleep(0.2)
        assert len(downstream.sent) == 1  # forwarded downstream; no response ever arrives

        test_conn.settimeout(5)
        data = read_message(test_conn, cfg.upstream.framing.to_dict())
        resp, _ = iso8583.decode(data, SPEC)
        assert resp["11"] == "000001"
        assert resp["39"] == "91"
    finally:
        dispatcher.drain_and_stop()
        up_conn.close()
        test_conn.close()


def test_submit_blocks_when_queue_is_full():
    dispatcher, cfg, downstream, stats = _make_dispatcher(queue_maxsize=1, pending_ttl_seconds=100)
    # Deliberately not calling dispatcher.start() - nothing drains the queue, so it fills up.

    up_conn, test_conn = socket.socketpair()
    write_lock = threading.Lock()
    try:
        req = {"t": "0100", "2": "4111111111111111", "11": "000001"}
        dispatcher.submit(RoutedMessage(req=req, up_conn=up_conn, up_write_lock=write_lock, up_addr=("x", 0)))

        second_submitted = threading.Event()

        def submit_second():
            req2 = {"t": "0100", "2": "4111111111111111", "11": "000002"}
            dispatcher.submit(RoutedMessage(req=req2, up_conn=up_conn, up_write_lock=write_lock, up_addr=("x", 0)))
            second_submitted.set()

        t = threading.Thread(target=submit_second, daemon=True)
        t.start()
        time.sleep(0.3)
        assert not second_submitted.is_set()

        dispatcher._queue.get_nowait()  # drain one slot
        t.join(timeout=2)
        assert second_submitted.is_set()
    finally:
        up_conn.close()
        test_conn.close()


def test_stan_collision_is_logged(caplog):
    dispatcher, cfg, downstream, stats = _make_dispatcher(pending_ttl_seconds=100)
    dispatcher.start()

    up_conn, test_conn = socket.socketpair()
    write_lock = threading.Lock()
    try:
        next_stan = str((dispatcher._stan_counter + 1) % 1_000_000).zfill(6)
        with dispatcher._pending_lock:
            dispatcher._pending[next_stan] = PendingEntry(up_conn, write_lock, "000000", time.monotonic())

        with caplog.at_level(logging.ERROR):
            req = {"t": "0100", "2": "4111111111111111", "11": "000001"}
            dispatcher.submit(RoutedMessage(req=req, up_conn=up_conn, up_write_lock=write_lock, up_addr=("x", 0)))
            time.sleep(0.3)

        assert any("still outstanding" in rec.message for rec in caplog.records)
    finally:
        dispatcher.drain_and_stop()
        up_conn.close()
        test_conn.close()


def test_pending_snapshot_reports_age_oldest_first():
    dispatcher, cfg, downstream, stats = _make_dispatcher(pending_ttl_seconds=100)

    up_conn, test_conn = socket.socketpair()
    write_lock = threading.Lock()
    try:
        now = time.monotonic()
        with dispatcher._pending_lock:
            dispatcher._pending["000001"] = PendingEntry(up_conn, write_lock, "100001", now - 5)
            dispatcher._pending["000002"] = PendingEntry(up_conn, write_lock, "100002", now - 1)

        snapshot = dispatcher.pending_snapshot()
        assert [e["router_stan"] for e in snapshot] == ["000001", "000002"]
        assert snapshot[0]["upstream_stan"] == "100001"
        assert snapshot[0]["age_seconds"] > snapshot[1]["age_seconds"]
    finally:
        up_conn.close()
        test_conn.close()


def test_drain_and_stop_logs_and_clears_abandoned_pending(caplog):
    dispatcher, cfg, downstream, stats = _make_dispatcher(pending_ttl_seconds=100)
    dispatcher.start()

    up_conn, test_conn = socket.socketpair()
    write_lock = threading.Lock()
    try:
        with dispatcher._pending_lock:
            dispatcher._pending["000042"] = PendingEntry(up_conn, write_lock, "100042", time.monotonic())

        with caplog.at_level(logging.WARNING):
            dispatcher.drain_and_stop()

        assert dispatcher._pending == {}
        messages = [rec.message for rec in caplog.records]
        assert any("router_stan 000042 still pending" in m for m in messages)
        assert any("abandoned 1 pending transaction" in m for m in messages)
        stan_record = next(rec for rec in caplog.records if "000042 still pending" in rec.message)
        assert stan_record.router_stan == "000042"
    finally:
        up_conn.close()
        test_conn.close()


def test_trace_capture_round_trip():
    dispatcher, cfg, downstream, stats = _make_dispatcher(pending_ttl_seconds=100)

    up_conn, test_conn = socket.socketpair()
    write_lock = threading.Lock()
    try:
        dispatcher.trace.arm(1)

        req = {"t": "0100", "2": "4111111111111111", "3": "000000", "4": "000000000100", "11": "000042"}
        msg = RoutedMessage(req=req, up_conn=up_conn, up_write_lock=write_lock, up_addr=("x", 0), raw=b"\xaa\xbb")
        dispatcher._process(msg)

        router_stan = next(iter(dispatcher._pending))
        assert router_stan == "000001"

        resp = {"t": "0110", "11": router_stan, "39": "00"}
        dispatcher.handle_response(resp, raw=b"\xcc\xdd")

        snap = dispatcher.trace.snapshot()
        assert len(snap["entries"]) == 1
        entry = snap["entries"][0]
        assert entry["router_stan"] == router_stan
        assert entry["upstream_stan"] == "000042"
        stages = [h["stage"] for h in entry["hops"]]
        # crypto_call appears once per leg (validate_0100 on the way down, validate_0110 on the
        # way back) - FakeCrypto returns "" (a no-op enrichment) but the hop is still recorded.
        assert stages == [
            "upstream_recv", "crypto_call", "downstream_send",
            "downstream_recv", "crypto_call", "upstream_send",
        ]
        assert entry["hops"][0]["wire_hex"] == "aabb"
        assert entry["hops"][3]["wire_hex"] == "ccdd"
        assert snap["armed"] is False  # count of 1 exhausted
    finally:
        up_conn.close()
        test_conn.close()


def test_latency_recorded_for_full_round_trip():
    dispatcher, cfg, downstream, stats = _make_dispatcher(pending_ttl_seconds=100)
    dispatcher.start()

    up_conn, test_conn = socket.socketpair()
    write_lock = threading.Lock()
    try:
        req = {"t": "0100", "2": "4111111111111111", "3": "000000", "4": "000000000100", "11": "000042"}
        # submit(), not _process() directly - queue_wait is only recorded in _worker_loop, which
        # only runs on the real dequeue path.
        dispatcher.submit(RoutedMessage(req=req, up_conn=up_conn, up_write_lock=write_lock, up_addr=("x", 0)))

        deadline = time.time() + 2
        while time.time() < deadline and not dispatcher._pending:
            time.sleep(0.05)
        router_stan = next(iter(dispatcher._pending))

        resp = {"t": "0110", "11": router_stan, "39": "00"}
        dispatcher.handle_response(resp)

        snap = stats.snapshot()
        for name in ("queue_wait", "crypto_rtt", "downstream_rtt", "total"):
            assert name in snap["latency"], f"missing latency bucket: {name}"
            assert snap["latency"][name]["count"] >= 1
        # one crypto_rtt sample per leg: validate_0100 on the way down, validate_0110 on the way back
        assert snap["latency"]["crypto_rtt"]["count"] == 2
    finally:
        dispatcher.drain_and_stop()
        up_conn.close()
        test_conn.close()


def test_purge_drops_queued_and_pending_counts():
    dispatcher, cfg, downstream, stats = _make_dispatcher(queue_maxsize=5, pending_ttl_seconds=100)
    # No start() - queue stays populated with nothing draining it.

    up_conn, test_conn = socket.socketpair()
    write_lock = threading.Lock()
    try:
        for i in range(3):
            req = {"t": "0100", "2": "4111111111111111", "11": str(i).zfill(6)}
            dispatcher.submit(RoutedMessage(req=req, up_conn=up_conn, up_write_lock=write_lock, up_addr=("x", 0)))

        with dispatcher._pending_lock:
            dispatcher._pending["999999"] = PendingEntry(up_conn, write_lock, "000000", time.monotonic())

        result = dispatcher.purge()
        assert result["dropped_queue"] == 3
        assert result["dropped_pending"] == 1
        assert dispatcher._queue.qsize() == 0
        assert len(dispatcher._pending) == 0
    finally:
        up_conn.close()
        test_conn.close()

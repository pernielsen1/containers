import logging
import os
import socket
import threading
import time

import iso8583

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
    def validate(self, endpoint, pan, f47):
        return ""


def _make_cfg(**overrides):
    framing = Framing(header_hex="", length_field_type="ASCII", length_field_bytes=4)
    upstream = UpstreamConfig(port=15000, framing=framing)
    downstream = DownstreamConfig(
        host="localhost", port=15001, irm_id=to_ebcdic("IRM0001", 8), client_id=to_ebcdic("CLIENT01", 8)
    )
    crypto = CryptoConfig(host="localhost", port=15002)
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

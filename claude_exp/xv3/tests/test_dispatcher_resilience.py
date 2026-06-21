import json
import logging
import socket
import threading
import time

import pytest

from router.config import RouterConfig
from router.dispatcher import Dispatcher, RoutedMessage
from shared.framing import read_message
from shared.ims_connect import read_request
from shared.stats import Stats


class FakeDownstream:
    def __init__(self, raise_on_send=False):
        self.frames = []
        self.raise_on_send = raise_on_send

    def send(self, frame):
        if self.raise_on_send:
            raise OSError("downstream unavailable")
        self.frames.append(frame)


class FakeCrypto:
    def __init__(self, result=""):
        self.result = result
        self.calls = []

    def validate(self, endpoint, pan, f47):
        self.calls.append((endpoint, pan, f47))
        return self.result


def make_cfg(**overrides):
    cfg = RouterConfig.from_file("router/router_1/config.json")
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def make_dispatcher(cfg=None, downstream=None, crypto=None, **cfg_overrides):
    cfg = cfg or make_cfg(**cfg_overrides)
    with open(cfg.iso_spec) as f:
        spec = json.load(f)
    downstream = downstream or FakeDownstream()
    crypto = crypto or FakeCrypto()
    stats = Stats()
    reconnect_event = threading.Event()
    dispatcher = Dispatcher(cfg, downstream, crypto, spec, stats, reconnect_event)
    return dispatcher, downstream, crypto, stats, reconnect_event


def make_upstream_conn():
    a, b = socket.socketpair()
    return a, b, threading.Lock()


def make_routed_message(stan="000001"):
    up_conn, peer_conn, lock = make_upstream_conn()
    req = {"t": "0100", "2": "4111111111111111", "3": "000000", "4": "000000000100", "11": stan}
    msg = RoutedMessage(req=req, up_conn=up_conn, up_write_lock=lock, up_addr=("127.0.0.1", 1234))
    return msg, peer_conn


def test_submit_blocks_when_queue_full():
    dispatcher, _, _, _, _ = make_dispatcher(queue_maxsize=1)
    msg1, _ = make_routed_message("000001")
    msg2, _ = make_routed_message("000002")

    dispatcher.submit(msg1)  # fills the queue, no workers draining it

    done = threading.Event()

    def submit_second():
        dispatcher.submit(msg2)
        done.set()

    t = threading.Thread(target=submit_second, daemon=True)
    t.start()
    t.join(timeout=0.3)
    assert not done.is_set()  # still blocked — queue is bounded at maxsize=1

    dispatcher._queue.get()  # drain one slot
    t.join(timeout=2)
    assert done.is_set()


def test_process_0100_calls_crypto_and_forwards_to_downstream():
    crypto = FakeCrypto(result='{"response_code":"00"}')
    dispatcher, downstream, crypto, stats, _ = make_dispatcher(crypto=crypto)
    msg, _ = make_routed_message("000042")

    dispatcher._process(msg)

    assert crypto.calls == [("validate_0100", "4111111111111111", "")]
    assert len(downstream.frames) == 1
    irm_f0, client_id, transcode, iso_data = read_request_from_bytes(downstream.frames[0])
    assert irm_f0 == 0x00

    pending = list(dispatcher._pending.values())
    assert len(pending) == 1
    assert pending[0].upstream_stan == "000042"
    assert stats.snapshot()["gauges"]["pending_count"] == 1


def test_process_0120_skips_crypto_call():
    def boom(*args, **kwargs):
        raise AssertionError("crypto should not be called for 0120 advice")

    crypto = FakeCrypto()
    crypto.validate = boom
    dispatcher, downstream, _, _, _ = make_dispatcher(crypto=crypto)

    up_conn, _, lock = make_upstream_conn()
    req = {"t": "0120", "2": "4111111111111111", "11": "000001", "39": "00"}
    msg = RoutedMessage(req=req, up_conn=up_conn, up_write_lock=lock, up_addr=("x", 1))

    dispatcher._process(msg)  # must not raise
    assert len(downstream.frames) == 1


def test_stan_collision_logged_at_error(caplog):
    dispatcher, downstream, _, _, _ = make_dispatcher()
    dispatcher._next_stan = lambda: "000000"

    msg1, _ = make_routed_message("000001")
    msg2, _ = make_routed_message("000002")

    with caplog.at_level(logging.ERROR):
        dispatcher._process(msg1)
        dispatcher._process(msg2)

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("000000" in r.message for r in error_records)
    # second entry overwrote the first under the same router_stan
    assert len(dispatcher._pending) == 1
    assert dispatcher._pending["000000"].upstream_stan == "000002"


def test_handle_response_restores_upstream_stan_and_calls_crypto():
    crypto = FakeCrypto(result='{"response_code":"00","arpc":"abc"}')
    dispatcher, downstream, crypto, stats, _ = make_dispatcher(crypto=crypto)
    msg, peer_conn = make_routed_message("000042")

    dispatcher._process(msg)
    router_stan = next(iter(dispatcher._pending))

    resp = {"t": "0110", "2": "4111111111111111", "11": router_stan, "39": "00"}
    dispatcher.handle_response(resp)

    assert crypto.calls[-1][0] == "validate_0110"
    assert router_stan not in dispatcher._pending
    assert stats.snapshot()["gauges"]["pending_count"] == 0

    framing_cfg = dispatcher.cfg.upstream.framing.to_dict()
    written = read_message(peer_conn, framing_cfg)
    import iso8583

    decoded, _ = iso8583.decode(written, dispatcher.spec)
    assert decoded["11"] == "000042"  # original upstream STAN restored


def test_handle_response_unknown_stan_logs_warning(caplog):
    dispatcher, _, _, _, _ = make_dispatcher()
    resp = {"t": "0110", "11": "999999", "39": "00"}
    with caplog.at_level(logging.WARNING):
        dispatcher.handle_response(resp)  # must not raise
    assert any("999999" in r.message for r in caplog.records)


def test_purge_drops_queue_and_pending():
    dispatcher, downstream, _, stats, _ = make_dispatcher()
    msg1, _ = make_routed_message("000001")
    msg2, _ = make_routed_message("000002")
    dispatcher._queue.put(msg1)
    dispatcher._queue.put(msg2)
    dispatcher._process(msg1)  # adds a pending entry

    result = dispatcher.purge()

    assert result == {"queue_dropped": 2, "pending_dropped": 1}
    assert dispatcher._queue.qsize() == 0
    assert len(dispatcher._pending) == 0
    assert stats.snapshot()["gauges"]["pending_count"] == 0


def test_pending_reaper_expires_and_declines():
    dispatcher, downstream, _, _, _ = make_dispatcher(pending_ttl_seconds=0)
    msg, peer_conn = make_routed_message("000042")
    dispatcher._process(msg)

    dispatcher.start()
    try:
        peer_conn.settimeout(3)
        framing_cfg = dispatcher.cfg.upstream.framing.to_dict()
        written = read_message(peer_conn, framing_cfg)
        import iso8583

        decoded, _ = iso8583.decode(written, dispatcher.spec)
        assert decoded["11"] == "000042"
        assert decoded["39"] == "91"
    finally:
        dispatcher.drain_and_stop()


def read_request_from_bytes(frame: bytes):
    a, b = socket.socketpair()
    try:
        a.sendall(frame)
        return read_request(b)
    finally:
        a.close()
        b.close()

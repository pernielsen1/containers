import sys
import os
import socket
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import iso8583

from shared.iso_utils import load_spec
from shared.stats import Stats
from router.dispatcher import Dispatcher, RoutedMessage, PendingEntry
from router.config import RouterConfig


SPEC_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test_spec.json")
SPEC = load_spec(SPEC_PATH)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class FakeDownstream:
    def __init__(self):
        self.sent = []
        self.fail = False
        self._lock = threading.Lock()

    def send(self, frame):
        if self.fail:
            raise OSError("fake downstream fail")
        with self._lock:
            self.sent.append(frame)

    def recv(self):
        time.sleep(10)


class FakeCrypto:
    def validate(self, endpoint, pan, f47):
        return f47


class FakeCfg:
    queue_maxsize = 10
    pending_ttl_seconds = 1
    worker_threads = 2
    crypto_breaker_threshold = 5
    crypto_breaker_cooldown_seconds = 30

    class upstream:
        class framing:
            header_hex = ""
            length_field_type = "ASCII"
            length_field_bytes = 4

            @staticmethod
            def to_dict():
                return {"header_hex": "", "length_field_type": "ASCII", "length_field_bytes": 4}

    class downstream:
        irm_id = b"IRM_ID01"
        client_id = b"CLIENT01"


def make_dispatcher(ds=None, ttl=30, maxsize=10):
    if ds is None:
        ds = FakeDownstream()
    cfg = FakeCfg()
    cfg.pending_ttl_seconds = ttl
    cfg.queue_maxsize = maxsize
    stats = Stats()
    recon = threading.Event()
    d = Dispatcher(cfg, ds, FakeCrypto(), SPEC, stats, recon)
    return d, ds, stats, recon


def make_upstream_pair():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    client = socket.create_connection(("127.0.0.1", port))
    server_conn, _ = srv.accept()
    srv.close()
    return client, server_conn


def test_bounded_queue_blocks():
    d, ds, stats, recon = make_dispatcher(maxsize=2)
    # Make downstream very slow to keep queue full
    block = threading.Event()
    original_send = ds.send

    def slow_send(frame):
        block.wait(timeout=2)
        original_send(frame)

    ds.send = slow_send
    d.start()

    lock = threading.Lock()
    msg = RoutedMessage(
        req={"t": "0100", "2": "4111111111111111", "11": "000001", "3": "000000", "4": "000000000100"},
        up_conn=None, up_write_lock=lock, up_addr=("127.0.0.1", 9999),
    )

    # Fill queue
    submitted = []
    def submit_many():
        for i in range(5):
            d.submit(msg)
            submitted.append(i)

    t = threading.Thread(target=submit_many, daemon=True)
    t.start()
    time.sleep(0.3)
    # Not all submitted yet — queue is bounded at 2 + workers draining
    block.set()
    t.join(timeout=3)


def test_pending_ttl_expiry():
    client_sock, server_sock = make_upstream_pair()
    lock = threading.Lock()

    d, ds, stats, recon = make_dispatcher(ttl=1)
    d.start()

    # Manually insert a stale pending entry
    import time as _time
    entry = PendingEntry(
        up_conn=server_sock,
        up_write_lock=lock,
        upstream_stan="000099",
        created_at=_time.monotonic() - 5,  # already expired
    )
    with d._pending_lock:
        d._pending["999999"] = entry
        stats.set_gauge("pending_count", len(d._pending))

    # Wait for reaper
    time.sleep(2.5)

    # Should have received a decline
    client_sock.settimeout(3)
    try:
        data = client_sock.recv(4096)
        assert len(data) > 0
        # Strip framing and decode
        payload = data[4:]  # skip ASCII length prefix
        resp, _ = iso8583.decode(payload, SPEC)
        assert resp.get("t") == "0110"
        assert resp.get("39") == "91"
    finally:
        client_sock.close()
        server_sock.close()
        d.drain_and_stop()


def test_stan_collision_logged(caplog):
    import logging
    d, ds, stats, recon = make_dispatcher()
    d.start()

    lock = threading.Lock()
    entry = PendingEntry(
        up_conn=None, up_write_lock=lock,
        upstream_stan="000001", created_at=time.monotonic(),
    )
    with d._pending_lock:
        d._pending["000001"] = entry

    # Force STAN counter to produce "000001"
    with d._stan_lock:
        d._stan_counter = 0  # next call returns 000001

    msg = RoutedMessage(
        req={"t": "0100", "2": "4111111111111111", "11": "000001", "3": "000000", "4": "000000000100"},
        up_conn=None, up_write_lock=lock, up_addr=("127.0.0.1", 9999),
    )

    with caplog.at_level(logging.ERROR):
        d._process(msg)

    assert any("collision" in r.message.lower() or "collision" in r.getMessage().lower()
               for r in caplog.records)

    d.drain_and_stop()


def test_purge_clears_pending_and_queue():
    d, ds, stats, recon = make_dispatcher()
    # Don't start workers — leave queue full

    lock = threading.Lock()
    entry = PendingEntry(
        up_conn=None, up_write_lock=lock,
        upstream_stan="000001", created_at=time.monotonic(),
    )
    with d._pending_lock:
        d._pending["000001"] = entry
        d._pending["000002"] = entry

    msg = RoutedMessage(
        req={"t": "0100", "2": "4111111111111111", "11": "000001", "3": "000000", "4": "000000000100"},
        up_conn=None, up_write_lock=lock, up_addr=("127.0.0.1", 9999),
    )
    # Enqueue without blocking (workers not started)
    for _ in range(3):
        try:
            d._queue.put_nowait(msg)
        except Exception:
            pass

    result = d.purge()
    assert result["dropped_pending"] == 2
    assert result["dropped_queue"] == 3
    assert len(d._pending) == 0
    assert d._queue.empty()

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.stats import Stats


def test_initial_snapshot():
    s = Stats()
    snap = s.snapshot()
    assert snap["sent_total"] == 0
    assert snap["recv_total"] == 0
    assert snap["seconds_since_last_recv"] is None
    assert snap["last_recv_datetime"] is None


def test_record_sent_recv():
    s = Stats()
    s.record_sent()
    s.record_sent()
    s.record_recv()
    snap = s.snapshot()
    assert snap["sent_total"] == 2
    assert snap["recv_total"] == 1
    assert snap["sent_30s"] == 2
    assert snap["recv_30s"] == 1
    assert snap["seconds_since_last_recv"] is not None


def test_connections():
    s = Stats()
    s.set_connection("upstream", True)
    s.set_connection("downstream", False)
    snap = s.snapshot()
    assert snap["connections"]["upstream"] is True
    assert snap["connections"]["downstream"] is False


def test_gauges():
    s = Stats()
    s.set_gauge("queue_depth", 42)
    snap = s.snapshot()
    assert snap["gauges"]["queue_depth"] == 42


def test_yellow_threshold():
    s = Stats(yellow_threshold_seconds=30)
    snap = s.snapshot()
    assert snap["yellow_threshold_seconds"] == 30


def test_window_counts():
    s = Stats()
    s.record_recv()
    snap = s.snapshot()
    assert snap["recv_30s"] == 1
    assert snap["recv_60s"] == 1
    assert snap["recv_180s"] == 1
    assert snap["recv_1800s"] == 1

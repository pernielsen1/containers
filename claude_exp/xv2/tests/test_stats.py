import time
import threading
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared.stats import Stats


def test_initial_snapshot_is_zero():
    s = Stats()
    snap = s.snapshot()
    for window in [30, 60, 180, 1800]:
        assert snap[f"sent_{window}s"] == 0
        assert snap[f"recv_{window}s"] == 0


def test_sent_increments():
    s = Stats()
    s.record_sent()
    s.record_sent()
    snap = s.snapshot()
    assert snap["sent_30s"] == 2
    assert snap["sent_1800s"] == 2


def test_recv_increments():
    s = Stats()
    s.record_recv()
    snap = s.snapshot()
    assert snap["recv_30s"] == 1


def test_sent_and_recv_independent():
    s = Stats()
    s.record_sent()
    s.record_sent()
    s.record_recv()
    snap = s.snapshot()
    assert snap["sent_30s"] == 2
    assert snap["recv_30s"] == 1


def test_old_events_excluded_from_short_window(monkeypatch):
    s = Stats()
    fake_time = [0.0]
    monkeypatch.setattr("shared.stats.time_func", lambda: fake_time[0])

    fake_time[0] = 0.0
    s.record_sent()   # t=0, outside 30s window when now=35

    fake_time[0] = 35.0
    s.record_sent()   # t=35, inside all windows

    snap = s.snapshot()
    assert snap["sent_30s"] == 1    # only t=35 in window
    assert snap["sent_60s"] == 2    # both in 60s window


def test_events_pruned_beyond_max_window(monkeypatch):
    s = Stats()
    fake_time = [0.0]
    monkeypatch.setattr("shared.stats.time_func", lambda: fake_time[0])

    fake_time[0] = 0.0
    s.record_sent()   # will fall out of 1800s window

    fake_time[0] = 1801.0
    s.record_sent()   # fresh event

    snap = s.snapshot()
    assert snap["sent_1800s"] == 1   # old event pruned


def test_thread_safety():
    s = Stats()
    threads = [threading.Thread(target=s.record_sent) for _ in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert s.snapshot()["sent_30s"] == 100


def test_snapshot_keys():
    s = Stats()
    snap = s.snapshot()
    expected = {f"{d}_{w}s" for d in ("sent", "recv") for w in (30, 60, 180, 1800)}
    assert set(snap.keys()) == expected

import time

from shared.stats import Stats


def test_totals_and_windows():
    stats = Stats()
    for _ in range(5):
        stats.record_sent()
    for _ in range(3):
        stats.record_recv()

    snap = stats.snapshot()
    assert snap["sent_total"] == 5
    assert snap["recv_total"] == 3
    assert snap["sent_30s"] == 5
    assert snap["recv_30s"] == 3
    assert snap["sent_1800s"] == 5
    assert snap["recv_1800s"] == 3


def test_seconds_since_last_recv_and_datetime():
    stats = Stats()
    assert stats.snapshot()["seconds_since_last_recv"] is None
    assert stats.snapshot()["last_recv_datetime"] is None

    stats.record_recv()
    snap = stats.snapshot()
    assert snap["seconds_since_last_recv"] >= 0
    assert len(snap["last_recv_datetime"]) == 8  # HH:MM:SS


def test_yellow_threshold_only_when_set():
    stats = Stats()
    assert "yellow_threshold_seconds" not in stats.snapshot()

    stats2 = Stats(yellow_threshold_seconds=40)
    assert stats2.snapshot()["yellow_threshold_seconds"] == 40


def test_connections_and_gauges_only_when_used():
    stats = Stats()
    snap = stats.snapshot()
    assert "connections" not in snap
    assert "gauges" not in snap

    stats.set_connection("upstream", True)
    stats.set_gauge("queue_depth", 7)
    snap = stats.snapshot()
    assert snap["connections"] == {"upstream": True}
    assert snap["gauges"] == {"queue_depth": 7}


def test_window_excludes_old_entries():
    stats = Stats()
    stats.record_sent()
    # Manually age the recorded timestamp past the 30s window but within 60s.
    stats._sent_times[0] -= 45
    snap = stats.snapshot()
    assert snap["sent_30s"] == 0
    assert snap["sent_60s"] == 1
    assert snap["sent_total"] == 1


def test_thread_safety_smoke():
    import threading

    stats = Stats()

    def hammer():
        for _ in range(200):
            stats.record_sent()
            stats.record_recv()

    threads = [threading.Thread(target=hammer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    snap = stats.snapshot()
    assert snap["sent_total"] == 800
    assert snap["recv_total"] == 800

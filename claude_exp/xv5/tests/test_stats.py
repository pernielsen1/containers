from shared.stats import Stats


def test_counters_and_windows():
    s = Stats(yellow_threshold_seconds=5)
    for _ in range(3):
        s.record_sent()
    for _ in range(2):
        s.record_recv()

    snap = s.snapshot()
    assert snap["sent_total"] == 3
    assert snap["recv_total"] == 2
    for window in (30, 60, 180, 1800):
        assert snap[f"sent_{window}s"] == 3
        assert snap[f"recv_{window}s"] == 2
    assert snap["last_recv_datetime"] is not None
    assert snap["seconds_since_last_recv"] is not None
    assert snap["seconds_since_last_recv"] < 1
    assert snap["yellow_threshold_seconds"] == 5


def test_connections_and_gauges():
    s = Stats()
    s.set_connection("upstream", True)
    s.set_gauge("queue_depth", 4)
    snap = s.snapshot()
    assert snap["connections"] == {"upstream": True}
    assert snap["gauges"] == {"queue_depth": 4}


def test_no_recv_yet_and_no_optional_keys():
    s = Stats()
    snap = s.snapshot()
    assert snap["seconds_since_last_recv"] is None
    assert snap["last_recv_datetime"] is None
    assert "yellow_threshold_seconds" not in snap
    assert "connections" not in snap
    assert "gauges" not in snap

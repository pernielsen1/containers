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
    assert "latency" not in snap


def test_latency_percentiles():
    s = Stats()
    # 1..100 ms so percentiles are easy to reason about
    for v in range(1, 101):
        s.record_latency("downstream_rtt", float(v))

    snap = s.snapshot()
    bucket = snap["latency"]["downstream_rtt"]
    assert bucket["count"] == 100
    assert bucket["min_ms"] == 1.0
    assert bucket["max_ms"] == 100.0
    assert 49 <= bucket["p50_ms"] <= 51
    assert 94 <= bucket["p95_ms"] <= 96


def test_latency_buckets_are_independent():
    s = Stats()
    s.record_latency("queue_wait", 1.0)
    s.record_latency("crypto_rtt", 5.0)
    snap = s.snapshot()
    assert set(snap["latency"].keys()) == {"queue_wait", "crypto_rtt"}
    assert snap["latency"]["queue_wait"]["count"] == 1
    assert snap["latency"]["crypto_rtt"]["count"] == 1


def test_latency_bucket_bounded_by_count():
    s = Stats()
    for v in range(3000):
        s.record_latency("total", float(v))
    snap = s.snapshot()
    # only the most recent _LATENCY_MAXLEN (2000) samples are kept
    assert snap["latency"]["total"]["count"] == 2000
    assert snap["latency"]["total"]["min_ms"] == 1000.0
    assert snap["latency"]["total"]["max_ms"] == 2999.0

from router.trace import TraceRecorder


def test_disarmed_by_default():
    trace = TraceRecorder()
    assert trace.armed is False
    assert trace.start("000001", "100001", "4111111111111111", "0100", b"\x01\x02") is False
    assert trace.snapshot() == {"armed": False, "remaining": 0, "entries": []}


def test_arm_captures_and_auto_disarms_after_count():
    trace = TraceRecorder()
    trace.arm(1)
    assert trace.armed is True

    started = trace.start("000001", "100001", "4111111111111111", "0100", b"\xde\xad")
    assert started is True
    assert trace.armed is False  # count exhausted

    # a second transaction shouldn't be captured now that the count is used up
    assert trace.start("000002", "100002", "4111111111111111", "0100", b"\xbe\xef") is False


def test_hop_and_finish_build_full_entry():
    trace = TraceRecorder()
    trace.arm(1)
    trace.start("000001", "100001", "4111111111111111", "0100", b"\x01\x02")
    trace.hop("000001", "crypto_call", crypto_ms=1.5, enriched=True)
    trace.hop("000001", "downstream_send", raw=b"\x03\x04")
    trace.finish("000001")

    snap = trace.snapshot()
    assert snap["entries"], "finished trace should appear in snapshot entries"
    entry = snap["entries"][0]
    assert entry["router_stan"] == "000001"
    assert entry["upstream_stan"] == "100001"
    assert entry["pan"] == "4111111111111111"
    stages = [h["stage"] for h in entry["hops"]]
    assert stages == ["upstream_recv", "crypto_call", "downstream_send"]
    assert entry["hops"][0]["wire_hex"] == "0102"
    assert entry["hops"][2]["wire_hex"] == "0304"
    assert entry["hops"][1]["crypto_ms"] == 1.5
    assert "_started_at" not in entry


def test_hop_on_untracked_stan_is_a_noop():
    trace = TraceRecorder()
    trace.arm(5)
    # never called start() for this stan - simulates a transaction that wasn't selected by arm()
    trace.hop("999999", "downstream_recv", raw=b"\x00")
    assert trace.snapshot()["entries"] == []


def test_filter_by_upstream_stan():
    trace = TraceRecorder()
    trace.arm(5, stan="100002")
    assert trace.start("000001", "100001", "4111111111111111", "0100", b"") is False
    assert trace.start("000002", "100002", "4111111111111111", "0100", b"") is True


def test_filter_by_pan():
    trace = TraceRecorder()
    trace.arm(5, pan="4222222222222222")
    assert trace.start("000001", "100001", "4111111111111111", "0100", b"") is False
    assert trace.start("000002", "100002", "4222222222222222", "0100", b"") is True


def test_abandon_in_progress_marks_incomplete_and_clears():
    trace = TraceRecorder()
    trace.arm(1)
    trace.start("000001", "100001", "4111111111111111", "0100", b"\x01")

    abandoned = trace.abandon_in_progress()
    assert len(abandoned) == 1
    assert abandoned[0]["incomplete"] is True

    snap = trace.snapshot()
    assert len(snap["entries"]) == 1
    assert snap["entries"][0]["incomplete"] is True
    # in-progress table is cleared - a late hop() call for this stan is now a no-op
    trace.hop("000001", "downstream_recv")
    assert len(trace.snapshot()["entries"]) == 1


def test_rearming_clears_previous_filters():
    trace = TraceRecorder()
    trace.arm(1, stan="100001")
    trace.arm(3)  # re-arm without a filter
    assert trace.start("000001", "999999", "4111111111111111", "0100", b"") is True

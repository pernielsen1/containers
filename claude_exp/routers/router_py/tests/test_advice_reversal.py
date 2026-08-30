"""briefs/resilience_v2.md: a 0100 that never gets its 0110 back within advice_timeout_seconds
gets both a 0420 (reversal - "forget my 0100") and a 0120 (STIP advice - the decision upstream
made on the cardholder's behalf), each independently store-and-forward retried until its own ack
(0430/0130) or advice_max_retries is exhausted (then logged to error_csv).

Uses StubRouter (see stub_router.py) rather than the real router/downstream_host/crypto_host
stack - this is upstream_host's own protocol-level behavior, fully exercisable in isolation and
much faster/more deterministic than a live multi-actor scenario. Small amplifiers throughout
(advice_timeout_seconds=0.3, backoff x2, not the 1.0s/x15 production default) so a full
exhaustion cycle takes ~4.5s instead of ~14 hours - see resilience.md's Round 8 for why the
production default is so much steeper.
"""
import csv
import itertools
import os
import threading
import time

import iso8583
import pytest

from upstream_host.main import UpstreamHostSim
from upstream_shared.iso_utils import load_spec

from tests.stub_router import StubRouter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC_PATH = os.path.join(PROJECT_ROOT, "test_spec.json")
FRAMING = {"header_hex": "", "length_field_type": "ASCII", "length_field_bytes": 4}
SPEC = load_spec(SPEC_PATH)

# Ports must be globally unique across the whole pytest session (Flask's dev server threads have
# no clean shutdown hook, so a reused port can collide with a previous test's still-running
# thread) - a simple counter is enough since tests in this file never run concurrently.
_next_port = itertools.count(19500)


@pytest.fixture
def stub_and_upstream(tmp_path):
    router = StubRouter(SPEC, FRAMING, port=next(_next_port))
    router.start()

    cfg = {
        "name": "test_upstream",
        "type": "upstream",
        "command_port": next(_next_port),
        "router": {"host": "127.0.0.1", "port": router.port},
        "framing": FRAMING,
        "iso_spec": SPEC_PATH,
        "input_dir": str(tmp_path / "input"),
        "ping_0800_seconds": 3600,
        "error_csv": str(tmp_path / "error_0120_0420.csv"),
        "advice_timeout_seconds": 0.3,
        "advice_max_retries": 2,
        "advice_backoff_multiplier": 2.0,
    }
    os.makedirs(cfg["input_dir"], exist_ok=True)

    up = UpstreamHostSim(cfg)
    up.start()

    deadline = time.time() + 5
    while up._get_conn() is None and time.time() < deadline:
        time.sleep(0.05)
    assert up._get_conn() is not None, "upstream never connected to stub router"

    yield up, router, cfg

    up.stop_event.set()
    router.stop()


def _send_0100(up, conn, pan: str) -> str:
    stan = up._next_stan()
    row = {"2": pan, "3": "000000", "4": "000000000100"}
    msg = dict(row)
    msg["t"] = "0100"
    msg["11"] = stan
    with up.pending_lock:
        up.pending[stan] = row
    up.send_times[stan] = time.monotonic()
    up._write_frame(conn, bytes(iso8583.encode(msg, SPEC)[0]))
    return stan


def test_healthy_round_trip_never_triggers_advice(stub_and_upstream):
    up, router, cfg = stub_and_upstream
    conn = up._get_conn()
    _send_0100(up, conn, "4111111111111111")

    time.sleep(cfg["advice_timeout_seconds"] * 3)  # comfortably past the timeout if it were buggy
    with up.advice_lock:
        assert len(up.advice_pending) == 0


def test_timed_out_0100_sends_both_0420_and_0120_and_both_get_acked(stub_and_upstream):
    up, router, cfg = stub_and_upstream
    conn = up._get_conn()
    router.reply_policy["0100"] = False  # black-hole - simulates downstream never answering

    pan = "4222222222222222"
    _send_0100(up, conn, pan)

    time.sleep(cfg["advice_timeout_seconds"] * 2)
    assert sorted(router.received_mtis_for(pan)) == ["0100", "0120", "0420"]

    time.sleep(0.3)  # let the acks round-trip back
    with up.advice_lock:
        assert len(up.advice_pending) == 0


def test_unacked_advice_exhausts_retries_and_logs_to_error_csv(stub_and_upstream):
    up, router, cfg = stub_and_upstream
    conn = up._get_conn()
    router.reply_policy["0100"] = False
    router.reply_policy["0420"] = False
    router.reply_policy["0120"] = False

    pan = "5111111111111111"
    _send_0100(up, conn, pan)

    # advice_pending starts empty and is trivially "empty" before the timeout even fires - wait
    # for it to become non-empty (the 0420/0120 actually got sent) before treating "empty again"
    # as exhaustion rather than "nothing happened yet".
    started_deadline = time.time() + cfg["advice_timeout_seconds"] + 1.0
    while time.time() < started_deadline:
        with up.advice_lock:
            if len(up.advice_pending) > 0:
                break
        time.sleep(0.05)
    with up.advice_lock:
        assert len(up.advice_pending) == 2, "0420/0120 never started tracking"

    # Full exhaustion needs max_retries+1 growing intervals after the initial timeout - the
    # last retry still gets its own full wait window before being declared unacknowledged (same
    # reasoning as TCP's last retransmission timeout), so this isn't just timeout*retries.
    t = cfg["advice_timeout_seconds"]
    multiplier = cfg["advice_backoff_multiplier"]
    interval = t * multiplier
    total_wait = t
    for _ in range(cfg["advice_max_retries"] + 1):
        total_wait += interval
        interval *= multiplier
    total_wait += 1.0  # margin
    deadline = time.time() + total_wait
    while time.time() < deadline:
        with up.advice_lock:
            if len(up.advice_pending) == 0:
                break
        time.sleep(0.1)
    with up.advice_lock:
        assert len(up.advice_pending) == 0, "advice entries never gave up"
    # advice_pending is cleared (under the lock) a moment before _log_advice_error actually
    # writes the file - give that its own short grace window rather than racing it.
    time.sleep(0.3)

    with open(cfg["error_csv"], encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    assert sorted(r["mti"] for r in rows) == ["0120", "0420"]
    for r in rows:
        assert r["pan"] == pan
        assert r["retries"] == str(cfg["advice_max_retries"])
        assert r["reason"] == "no_ack_after_max_retries"


@pytest.fixture
def throttled_stub_and_upstream(tmp_path):
    """briefs/resilience_v2.md ("have been evaluating the scenario"): advice_reversal_percentage
    caps how much of upstream_host's send capacity 0120/0420 traffic can use while a 0100 stream
    is actively running - see UpstreamHostSim._dispatch_or_queue/_send_loop. Its own fixture
    since it needs a real _send_loop run (run_start_time/run_end_time set) for the throttle gate
    to engage at all - the other tests' `_send_0100` helper bypasses _send_loop entirely."""
    router = StubRouter(SPEC, FRAMING, port=next(_next_port))
    router.start()

    cfg = {
        "name": "test_upstream_throttled",
        "type": "upstream",
        "command_port": next(_next_port),
        "router": {"host": "127.0.0.1", "port": router.port},
        "framing": FRAMING,
        "iso_spec": SPEC_PATH,
        "input_dir": str(tmp_path / "input"),
        "ping_0800_seconds": 3600,
        "error_csv": str(tmp_path / "error_0120_0420.csv"),
        "advice_timeout_seconds": 0.05,
        "advice_max_retries": 5,
        "advice_backoff_multiplier": 2.0,
        "advice_reversal_percentage": 10,  # brief's own worked example: 1 advice send per 9 0100s
    }
    os.makedirs(cfg["input_dir"], exist_ok=True)

    up = UpstreamHostSim(cfg)
    up.start()

    deadline = time.time() + 5
    while up._get_conn() is None and time.time() < deadline:
        time.sleep(0.05)
    assert up._get_conn() is not None, "upstream never connected to stub router"

    yield up, router, cfg

    up.stop_event.set()
    router.stop()


def test_advice_reversal_percentage_throttles_advice_sends(throttled_stub_and_upstream):
    up, router, cfg = throttled_stub_and_upstream
    conn = up._get_conn()
    # Every 0100 times out (never acked) -> each fires a 0420+0120 registration; also blackhole
    # their acks so dispatched entries stay visible in advice_pending instead of clearing
    # themselves out mid-test.
    router.reply_policy["0100"] = False
    router.reply_policy["0420"] = False
    router.reply_policy["0120"] = False

    assert up._advice_ratio == 9  # round((100-10)/10)

    rows = [{"2": "4333333333333333", "3": "000000", "4": "000000000100"}]
    rate = 20.0
    duration = 1.0
    thread = threading.Thread(
        target=up._run_with_warmup, args=(conn, rows, rate, duration, 0.0), daemon=True
    )
    thread.start()
    thread.join(timeout=duration + 3)
    assert not thread.is_alive(), "stress run never finished"

    with up.advice_lock:
        registered = len(up.advice_pending)
        dispatched = sum(1 for e in up.advice_pending.values() if e["dispatched"])
        still_queued = len(up.advice_send_queue)
        queued_entries_flagged = sum(1 for e in up.advice_pending.values() if e["queued"])

    # Near-every 0100 timed out inside the 1s window (advice_timeout_seconds=0.05s), each
    # registering both a 0420 and a 0120 - far more than the throttle could actually dispatch.
    assert registered > 2 * (up.run_sent // 2), "expected most 0100s to have timed out by run end"
    assert still_queued > 0, "throttle never built a backlog - did it actually engage?"
    # Not a strict equality: _send_loop pops a stan off the queue, then writes the frame, then
    # flips dispatched=True/queued=False - a real (harmless) window where a just-popped entry is
    # momentarily counted in neither "still queued" nor "dispatched" yet.
    assert abs((registered - dispatched) - still_queued) <= 1
    assert abs(queued_entries_flagged - still_queued) <= 1
    # At most one advice dispatch per _advice_ratio 0100 sends, plus a little slack for whichever
    # send was mid-flight when the run ended.
    assert dispatched <= (up.run_sent // up._advice_ratio) + 1

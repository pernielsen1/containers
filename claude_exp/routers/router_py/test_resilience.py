#!/usr/bin/env python3
"""Resilience test suite - see routers/resilience.md.

Orchestrated in Python (not bash, unlike run_test.sh/stress_run.sh) because this suite needs to
kill and restart individual actors mid-run and poll their /stats between transitions - all
process-lifecycle logic here is reused directly from monitor/main.py (discover_actors/
launch_actor/stop_actor/is_running/wait_for_ready) rather than reimplemented, since that module
already solves "spawn/kill one named actor and know when it's really ready" for the monitor UI.

Both upstream_1 and upstream_2 (and their routers, router_1/router_2) are brought up regardless of
their config.json `is_active` flag - the whole point of this suite is exercising the two-upstream
topology, not the single-upstream default used elsewhere.

Usage: ./test_resilience.sh   (or: python3 test_resilience.py)
Output: console narration of each transition, plus routers/router_py/test_resilience.csv
(timestamp;actor;event).
"""
import os
import sys
import time
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from monitor.main import get_actor, is_running, launch_actor, stop_actor, wait_for_ready  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(PROJECT_ROOT, "test_csv_files", "test.csv")
CHAOS_CSV_FILE = os.path.join(PROJECT_ROOT, "test_csv_files", "chaos_no_response.csv")
TPS_CSV_FILE = os.path.join(PROJECT_ROOT, "test_csv_files", "tps_10pct_bad_card.csv")
REQUEST_LEG_OUTAGE_CSV_FILE = os.path.join(
    PROJECT_ROOT, "test_csv_files", "crypto_request_leg_outage.csv"
)
RESULT_CSV = os.path.join(PROJECT_ROOT, "test_resilience.csv")
# upstream_host/config.json's error_csv, resolved the same way load_config() resolves it -
# scenario_crypto_request_leg_outage_triggers_advice checks this stays empty (both 0420/0120
# get acked, not exhausted).
UPSTREAM_ERROR_CSV = os.path.join(PROJECT_ROOT, "..", "upstream_host", "error_0120_0420.csv")

# Default CryptoClient breaker settings (router/crypto_client.py) - not overridden by any
# router_1/router_2 config.json in this repo, so these constants match production behavior.
BREAKER_COOLDOWN_S = 30
PING_INTERVAL_S = 30  # upstream_host config.json's ping_0800_seconds, both upstream_1/upstream_2

# scenario_crypto_response_no_reply_queue_buildup: PAN 8888888888888888 is configured in
# simulators/crypto_host/config.json's no_response_pans to hang forever on validate_0110 only -
# see that scenario's docstring. response_worker_threads defaults to 8 and each hung call ties
# one up for ~10s (CryptoClient's 5s HTTP timeout, once on the first connection and once more on
# the single retry _send() does on any failure) before giving up - so drain capacity is roughly
# 8/10s = 0.8/s. Sending faster than that on this PAN alone should build a real backlog well
# within queue_maxsize's default of 1000 inside this window.
CHAOS_PAN = "8888888888888888"
QUEUE_BUILDUP_RATE_TPS = 10
QUEUE_BUILDUP_DURATION_S = 180
QUEUE_BUILDUP_POLL_INTERVAL_S = 10

# scenario_crypto_response_fire_and_forget_sustains_tps: Round 6 found that one card *always*
# failing its 0110 leg gets absorbed by the existing pending-TTL reaper. briefs/resilience_v2.md's
# follow-up asks the more realistic question - a realistic slice of traffic failing (10%, "which
# is a very high number") - and requires router_1/config.json's crypto_response_timeout_seconds
# (router/config.py, default 0.2s on this laptop) to actually be short, so a response-worker
# thread never blocks on a stuck validate_0110 call for more than ~2x that (one attempt +
# crypto_client.py's single retry-on-failure).
#
# The 10% itself is modeled as test *data*, not logic in crypto_host: crypto_host only ever needs
# to know "this PAN doesn't work" (no_response_pans, same static PAN-keyed mechanism as Round 6 -
# it's a dumb lookup so it stays trivially portable to the eventual C++ crypto_host). Which/how
# many cards are "bad" is upstream_host's concern as the traffic simulator -
# test_csv_files/tps_10pct_bad_card.csv cycles 9 good-card rows against 1 row of the existing
# Round-6 chaos PAN (8888888888888888, already configured in simulators/crypto_host/config.json).
TPS_TARGET = 100
TPS_DURATION_S = 60
TPS_POLL_INTERVAL_S = 10
TPS_BAD_CARD_FRACTION = 0.10  # matches tps_10pct_bad_card.csv's 1-in-10 row mix, for the printout
# Generous: a 462-item backlog (30s burst) measured draining in <5s once traffic stopped, so a
# full 60s run's larger backlog should clear well inside this - see scenario docstring.
TPS_DRAIN_TIMEOUT_S = 60

# scenario_crypto_request_leg_outage_triggers_advice (Round 8): PAN 7777777777777777 is configured
# in simulators/crypto_host/config.json's no_response_pans to hang on validate_0100 specifically -
# a stand-in for "crypto/HSM unreachable", the realistic trigger for STIP the user pointed at
# instead of killing downstream_host (which tears down the whole session before a 0100 can even be
# sent - see resilience.md's Round 8 write-up). While validate_0100 hangs, the router hasn't
# registered the transaction in _pending or forwarded it downstream yet, so upstream genuinely
# gets silence - its own advice_timeout_seconds (1.0s, production default) fires cleanly.
REQUEST_LEG_OUTAGE_PAN = "7777777777777777"
REQUEST_LEG_ADVICE_TIMEOUT_S = 20  # generous margin over the 1.0s advice timeout + ack round trip

launched = []  # actors this script itself started - only these get torn down at the end


def _now_str() -> str:
    return datetime.now().astimezone().strftime("%H:%M:%S")


def announce(action: str, min_s: float, max_s: float = None) -> None:
    """Prints an explicit 'about to wait' marker before every sleep/poll in this suite, so
    someone following the console live always knows what's happening next and how long to
    expect - never just a silent gap. max_s omitted (or equal to min_s) means a fixed-duration
    wait; given explicitly means a poll loop with a deadline, which may finish sooner."""
    if max_s is None or max_s == min_s:
        print(f"[{_now_str()}] WAITING: {action} (fixed {min_s:.0f}s)")
    else:
        print(f"[{_now_str()}] WAITING: {action} (at least {min_s:.0f}s, up to {max_s:.0f}s)")


def done_waiting(action: str, elapsed: float) -> None:
    print(f"[{_now_str()}] DONE: {action} (took {elapsed:.1f}s)")


def narrated_sleep(seconds: float, reason: str) -> None:
    announce(reason, seconds)
    start = time.time()
    time.sleep(seconds)
    done_waiting(reason, time.time() - start)


class CsvLog:
    def __init__(self, path):
        self.path = path
        if not os.path.exists(path):
            # BOM only belongs on the very first byte of the file - written once here, never on
            # an append, matching this repo's csv_results/*.csv convention.
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write("timestamp;actor;event\n")

    def log(self, actor, event):
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        line = f"{ts};{actor};{event}"
        print(line)
        with open(self.path, "a", encoding="utf-8", newline="") as f:
            f.write(line + "\n")


def start_actor(name, timeout=15):
    actor = get_actor(name)
    if actor is None:
        raise RuntimeError(f"unknown actor: {name}")
    if not is_running(name):
        launch_actor(actor)
        launched.append(actor)
    announce(f"waiting for {name} to become ready", 0, timeout)
    start = time.time()
    wait_for_ready(actor, timeout=timeout)
    done_waiting(f"{name} ready", time.time() - start)
    return actor


def kill_actor(name):
    actor = get_actor(name)
    stop_actor(actor)
    if actor in launched:
        launched.remove(actor)


def teardown():
    while launched:
        actor = launched.pop()
        try:
            stop_actor(actor)
            print(f"[teardown] stopped {actor['name']}")
        except Exception as e:
            print(f"[teardown] failed to stop {actor['name']}: {e}")


def stats(name):
    actor = get_actor(name)
    try:
        r = requests.get(f"http://127.0.0.1:{actor['command_port']}/stats", timeout=2)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None


def stress_stats(name):
    actor = get_actor(name)
    try:
        r = requests.get(f"http://127.0.0.1:{actor['command_port']}/stress_stats", timeout=2)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None


def totals(name):
    s = stats(name)
    if s is None:
        return None
    return (s.get("sent_total", 0), s.get("recv_total", 0))


def traffic_advanced(name, before):
    after = totals(name)
    if before is None or after is None:
        return False
    return after[0] > before[0] or after[1] > before[1]


def send_test_csv(upstream_name):
    """Uploads test_csv_files/test.csv to the given upstream and waits for all rows to round-trip
    - same protocol run_test.sh uses (upload, then poll /start until it stops 503'ing since a
    just-reconnected upstream can lag behind /stats reporting connected, then poll /results)."""
    actor = get_actor(upstream_name)
    port = actor["command_port"]
    with open(CSV_FILE, "rb") as f:
        requests.post(f"http://127.0.0.1:{port}/upload", files={"file": f}, timeout=5)

    announce(f"{upstream_name}: waiting for /start to accept (upstream must show connected)", 0, 15)
    poll_start = time.time()
    expected = None
    for _ in range(15):
        r = requests.get(f"http://127.0.0.1:{port}/start", timeout=3)
        if r.status_code == 200:
            expected = r.json().get("rows", 0)
            break
        time.sleep(1)
    if expected is None:
        done_waiting(f"{upstream_name}: /start never became available, giving up", time.time() - poll_start)
        return []
    done_waiting(f"{upstream_name}: /start accepted, {expected} row(s) queued", time.time() - poll_start)

    announce(f"{upstream_name}: waiting for {expected} row(s) to round-trip", 0, 15)
    poll_start = time.time()
    deadline = poll_start + 15
    results = []
    while time.time() < deadline:
        r = requests.get(f"http://127.0.0.1:{port}/results", timeout=3)
        if r.ok:
            results = r.json()
            if len(results) >= expected:
                break
        time.sleep(0.5)
    done_waiting(f"{upstream_name}: {len(results)}/{expected} row(s) round-tripped", time.time() - poll_start)
    return results


def summarize(results):
    if not results:
        return "no results received"
    return [{"pan": r.get("2"), "resp_39": r.get("resp_39"), "resp_47": r.get("resp_47")} for r in results]


def scenario_upstream_failover(log):
    print("\n=== SCENARIO: upstream failover (both upstream_1 and upstream_2 active) ===")
    print(
        f"    plan: start 6 actors -> settle 2s -> kill upstream_1, wait {PING_INTERVAL_S + 5}s "
        f"-> kill upstream_2, wait {PING_INTERVAL_S + 5}s -> recover both (~30s each)"
    )
    for name in ["crypto_host", "downstream_host", "router_1", "upstream_1", "router_2", "upstream_2"]:
        start_actor(name)
        log.log(name, "up")
    narrated_sleep(2, "letting both upstream connections settle before taking a baseline")

    before_u2 = totals("upstream_2")
    kill_actor("upstream_1")
    log.log("upstream_1", "down")
    narrated_sleep(PING_INTERVAL_S + 5, "confirming upstream_2's 0800 ping traffic keeps going without upstream_1")
    advanced = traffic_advanced("upstream_2", before_u2)
    verdict = "PASS" if advanced else "FAIL"
    log.log("upstream_2", f"ping_traffic_continued={advanced}")
    print(f"{verdict}: upstream_2 ping traffic continued while upstream_1 was down: {advanced}")

    kill_actor("upstream_2")
    log.log("upstream_2", "down")
    narrated_sleep(PING_INTERVAL_S + 5, "observing downstream_host with both upstreams down")
    ds_stats = stats("downstream_host")
    log.log("downstream_host", f"OBSERVED with both upstreams down: {ds_stats}")
    print(f"OBSERVED downstream_host stats with both upstreams down: {ds_stats}")

    start_actor("upstream_1")
    log.log("upstream_1", "up")
    results = send_test_csv("upstream_1")
    log.log("upstream_1", f"test.csv round-tripped {len(results)} rows: {summarize(results)}")
    print(f"upstream_1 recovery: {len(results)} rows round-tripped")

    start_actor("upstream_2")
    log.log("upstream_2", "up")
    results = send_test_csv("upstream_2")
    log.log("upstream_2", f"test.csv round-tripped {len(results)} rows: {summarize(results)}")
    print(f"upstream_2 recovery: {len(results)} rows round-tripped")


def scenario_downstream_failure(log):
    print("\n=== SCENARIO: downstream_host failure (open question in resilience.md) ===")
    print("    plan: kill downstream_host, wait 15s -> recover, wait 20s for auto-reconnect -> send test.csv (~30s)")
    kill_actor("downstream_host")
    log.log("downstream_host", "down")
    narrated_sleep(15, "observing router_1/router_2/upstream_1/upstream_2 with downstream_host down")
    observed = {
        "router_1": stats("router_1"),
        "router_2": stats("router_2"),
        "upstream_1": stats("upstream_1"),
        "upstream_2": stats("upstream_2"),
    }
    log.log("downstream_host", f"OBSERVED after 15s down: {observed}")
    print(f"OBSERVED with downstream_host down: {observed}")

    start_actor("downstream_host")
    log.log("downstream_host", "up")
    narrated_sleep(20, "waiting for router_1/router_2 to auto-reconnect (reestablish_seconds=10 + jitter)")
    results = send_test_csv("upstream_1")
    log.log("downstream_host", f"recovery test.csv round-tripped {len(results)} rows: {summarize(results)}")
    print(f"downstream_host recovery: {len(results)} rows round-tripped")


def scenario_stuck_pending_on_downstream_teardown(log):
    """Not the SIGSTOP/pause-resume variant resilience.md flags as a deferred follow-up (that one
    simulates a silent hang and turned out racy to script deterministically - see
    project_routers_monorepo memory). This is a plain, deterministic case: downstream_host is
    killed *before* sending, then upstream_1's own already-open connection (untouched - no
    fighting over router_1's single-client "server mode" slot, which is what an earlier, more
    complicated version of this scenario tripped over) is used to send test.csv. Every row gets
    genuinely stuck in router_1's pending map (there's nowhere for it to go), and this checks that
    the session teardown that follows (dispatcher.py's drain_and_stop, once the downstream
    receiver thread's recv() notices downstream_host is gone) reports the abandoned
    transaction(s) instead of silently dropping them - the gap found and fixed while building
    Phase 3 of the debug-tracing tooling (briefs/debug_trace_master.md)."""
    print("\n=== SCENARIO: transaction stuck in-flight when downstream_host dies mid-flight ===")
    print("    plan: kill downstream_host -> send test.csv (~15s, expected to hang) -> poll /logs for the "
          "abandonment line (up to 10s) -> recover, wait 20s -> send test.csv (~30s)")
    router = get_actor("router_1")

    kill_actor("downstream_host")
    log.log("downstream_host", "down (about to send a transaction with nowhere to go)")

    # send_test_csv uploads+starts test.csv on upstream_1's existing connection and polls for
    # results for up to 15s - downstream is dead so nothing will ever complete, but that gives
    # router_1's session plenty of time to notice and tear down mid-call.
    results = send_test_csv("upstream_1")
    log.log("upstream_1", f"results while downstream dead: {summarize(results)}")

    announce("polling router_1's /logs for the session-teardown abandonment line", 0, 10)
    poll_start = time.time()
    abandoned_logged = False
    deadline = poll_start + 10
    while time.time() < deadline and not abandoned_logged:
        try:
            logs = requests.get(f"http://127.0.0.1:{router['command_port']}/logs", timeout=3).json()
        except requests.RequestException:
            logs = []
        abandoned_logged = any("still pending" in entry.get("message", "") for entry in logs)
        if not abandoned_logged:
            time.sleep(1)
    done_waiting(f"abandonment logged={abandoned_logged}", time.time() - poll_start)
    log.log("router_1", f"session-teardown abandonment logged={abandoned_logged}")
    verdict = "PASS" if abandoned_logged else "FAIL"
    print(f"{verdict}: session teardown logged the abandoned transaction (dispatcher.py drain_and_stop)")

    start_actor("downstream_host")
    log.log("downstream_host", "up")
    narrated_sleep(20, "waiting for router_1 to auto-reconnect (reestablish_seconds=10 + jitter)")
    results = send_test_csv("upstream_1")
    log.log("downstream_host", f"recovery test.csv round-tripped {len(results)} rows: {summarize(results)}")


def scenario_crypto_host_failure(log):
    print("\n=== SCENARIO: crypto_host failure (open question in resilience.md) ===")
    print(f"    plan: kill crypto_host -> send test.csv (~30s) -> recover, wait {BREAKER_COOLDOWN_S + 5}s "
          f"for breaker cooldown -> send test.csv (~30s)")
    kill_actor("crypto_host")
    log.log("crypto_host", "down")
    results = send_test_csv("upstream_1")
    log.log("crypto_host", f"OBSERVED test.csv while down: {summarize(results)}")
    print(f"OBSERVED with crypto_host down: {summarize(results)}")

    start_actor("crypto_host")
    log.log("crypto_host", "up")
    narrated_sleep(BREAKER_COOLDOWN_S + 5, "letting CryptoClient's circuit breaker close again")
    results = send_test_csv("upstream_1")
    log.log("crypto_host", f"OBSERVED test.csv after recovery + breaker cooldown: {summarize(results)}")
    print(f"OBSERVED after crypto_host recovery: {summarize(results)}")


def scenario_crypto_response_no_reply_queue_buildup(log):
    """briefs/resilience_v2.md ("let's be more destructive build up a queue"): crypto_host is
    configured (simulators/crypto_host/config.json's no_response_pans) so PAN 8888888888888888
    validates fine on its *request* leg (validate_0100) but never gets a reply at all on its
    *response* leg (validate_0110) - a real hang, not a fast HTTP error, simulating a card whose
    crypto data makes response validation itself get stuck rather than fail cleanly. Drives
    sustained traffic using only that PAN (test_csv_files/chaos_no_response.csv, one row cycled
    by upstream_1's /start?rate=&duration= stress endpoint - the same mechanism stress_run.sh
    uses) and polls router_1/upstream_1 throughout.

    The brief's own framing is "my expectation is we will stop reading upstream at some point but
    let's see" - deliberately not assumed here. Tracing the code first: crypto.validate()'s
    failure path (router/crypto_client.py) never blocks forwarding - a "" result just leaves f47
    unenriched and the response still goes out - and dispatcher.py's response leg pops the
    _pending entry *before* the (possibly-hanging) crypto call, not after, so a stuck 0110 doesn't
    grow _pending. What can genuinely back up is _response_queue (submit_response(), bounded by
    queue_maxsize=1000): 8 response_worker_threads each tied up ~10s per hung call (5s HTTP
    timeout, once direct + once on _send()'s single retry) drain at roughly 0.8/s against
    QUEUE_BUILDUP_RATE_TPS arrivals - if that queue fills, the ds-receiver thread's
    submit_response() call blocks, which stops router_1 from reading *downstream*, not upstream
    (session.py's upstream- and downstream-recv loops are separate threads over separate
    sockets). Whether that ever actually propagates back to the upstream leg (e.g. via
    downstream_host itself stalling) is exactly the open question - hence logging connections/
    queue_depth/response_queue_depth/pending_count every poll instead of asserting a shape."""
    print("\n=== SCENARIO: crypto_host never replies on validate_0110 for one PAN - build up a queue ===")
    print(f"    plan: sustained {QUEUE_BUILDUP_RATE_TPS} TPS on PAN {CHAOS_PAN} for "
          f"{QUEUE_BUILDUP_DURATION_S}s, polling router_1/upstream_1 every "
          f"{QUEUE_BUILDUP_POLL_INTERVAL_S}s -> stop -> recovery check with ordinary test.csv")

    actor = get_actor("upstream_1")
    port = actor["command_port"]
    with open(CHAOS_CSV_FILE, "rb") as f:
        requests.post(f"http://127.0.0.1:{port}/upload", files={"file": f}, timeout=5)
    r = requests.get(
        f"http://127.0.0.1:{port}/start",
        params={"rate": QUEUE_BUILDUP_RATE_TPS, "duration": QUEUE_BUILDUP_DURATION_S},
        timeout=5,
    )
    log.log("upstream_1", f"chaos PAN stress start status={r.status_code} body={r.text}")
    print(f"upstream_1: stress start status={r.status_code} body={r.text}")

    upstream_ever_dropped = False
    deadline = time.time() + QUEUE_BUILDUP_DURATION_S
    while time.time() < deadline:
        time.sleep(min(QUEUE_BUILDUP_POLL_INTERVAL_S, max(0.0, deadline - time.time())))
        r_stats = stats("router_1") or {}
        u_stats = stress_stats("upstream_1") or {}
        conns = r_stats.get("connections", {})
        gauges = r_stats.get("gauges", {})
        if conns.get("upstream") is False:
            upstream_ever_dropped = True
        msg = (
            f"router_1: connections={conns} queue_depth={gauges.get('queue_depth')} "
            f"response_queue_depth={gauges.get('response_queue_depth')} "
            f"pending_count={gauges.get('pending_count')} | upstream_1: sent={u_stats.get('sent')} "
            f"received={u_stats.get('received')} errors={u_stats.get('errors')}"
        )
        print(f"[{_now_str()}] {msg}")
        log.log("router_1", msg)

    narrated_sleep(5, "letting the stress run's tail settle before the recovery check")
    results = send_test_csv("upstream_1")
    recovered = len(results) == 3  # test.csv's 3 ordinary rows - none of them the chaos PAN
    verdict = "PASS" if recovered else "FAIL"
    log.log(
        "router_1",
        f"post-attack recovery verdict={verdict} rows={len(results)}/3 "
        f"upstream_connection_ever_dropped_during_attack={upstream_ever_dropped}",
    )
    print(f"{verdict}: post-attack test.csv round-tripped {len(results)}/3 row(s); "
          f"router_1's upstream connection ever dropped during the attack={upstream_ever_dropped}")


def scenario_crypto_response_fire_and_forget_sustains_tps(log):
    """briefs/resilience_v2.md's follow-up to Round 6: "having build up the queue - let's look at
    what happens in real world" - most transactions won't hit a stuck crypto response, but a
    realistic slice will (10% here, the brief's own "very high number" stress figure), and the
    router should still sustain its target TPS rather than let a slow backend throttle upstream
    traffic. Unlike scenario_crypto_response_no_reply_queue_buildup (one PAN, always fails, 10
    TPS), this drives a realistic mix (test_csv_files/tps_10pct_bad_card.csv - 9 good cards to 1
    known-bad card, cycled by upstream_1's /start?rate=&duration= stress endpoint) at TPS_TARGET.

    Deliberately not a probability toggle inside crypto_host: crypto_host only needs to know "this
    PAN doesn't work" (the existing PAN-keyed no_response_pans, unchanged from Round 6) - which
    cards are bad, and how many, is upstream_host's concern as the traffic simulator, expressed as
    plain test data rather than new simulator code.

    This only has a chance of working because router/session.py now gives the response leg its
    own short-timeout CryptoClient (crypto_response_timeout_seconds, briefs' "fire and forget...
    no one cares about the result anymore" once downstream has already answered) - with the old
    single 5s-timeout client shared by both legs, 10% of calls blocking ~10s each would have
    swamped the response-worker pool exactly like Round 6's dedicated-PAN attack did.

    Two things to check, not one: upstream's own send rate (does the attack ever throttle
    *sending*?) and whether responses actually keep pace end-to-end. They can diverge - upstream's
    send loop never blocks on replies, so a healthy achieved_tps alone doesn't prove the response
    side kept up; response_queue_depth/pending_count building a real backlog during the sustained
    attack is expected at this failure rate (confirmed: the response CryptoClient's own circuit
    breaker, shared threshold=5/cooldown=30s, trips and un-trips under a bad-card mix, so
    throughput is bursty rather than smooth) - what matters is whether that backlog is transient
    (drains once traffic stops) or a genuine stall. See TPS_DRAIN_TIMEOUT_S."""
    print("\n=== SCENARIO: ~10% of cards fail their crypto response leg - is 100 TPS still met? ===")
    print(f"    plan: sustained {TPS_TARGET} TPS on a 9-good/1-bad card mix for {TPS_DURATION_S}s, "
          f"polling every {TPS_POLL_INTERVAL_S}s -> recovery check with ordinary test.csv")

    actor = get_actor("upstream_1")
    port = actor["command_port"]
    with open(TPS_CSV_FILE, "rb") as f:
        requests.post(f"http://127.0.0.1:{port}/upload", files={"file": f}, timeout=5)
    r = requests.get(
        f"http://127.0.0.1:{port}/start",
        params={"rate": TPS_TARGET, "duration": TPS_DURATION_S},
        timeout=5,
    )
    log.log("upstream_1", f"TPS-under-chaos stress start status={r.status_code} body={r.text}")
    print(f"upstream_1: stress start status={r.status_code} body={r.text}")

    deadline = time.time() + TPS_DURATION_S
    last_stress = None
    while time.time() < deadline:
        time.sleep(min(TPS_POLL_INTERVAL_S, max(0.0, deadline - time.time())))
        r_stats = stats("router_1") or {}
        last_stress = stress_stats("upstream_1") or {}
        conns = r_stats.get("connections", {})
        gauges = r_stats.get("gauges", {})
        msg = (
            f"router_1: connections={conns} queue_depth={gauges.get('queue_depth')} "
            f"response_queue_depth={gauges.get('response_queue_depth')} "
            f"pending_count={gauges.get('pending_count')} | upstream_1: "
            f"achieved_tps={last_stress.get('achieved_tps')} sent={last_stress.get('sent')} "
            f"received={last_stress.get('received')} errors={last_stress.get('errors')}"
        )
        print(f"[{_now_str()}] {msg}")
        log.log("router_1", msg)

    final_stress = stress_stats("upstream_1") or last_stress or {}
    achieved_tps = final_stress.get("achieved_tps") or 0
    send_verdict = achieved_tps >= TPS_TARGET * 0.95
    log.log(
        "upstream_1",
        f"TPS-under-chaos send-side: achieved_tps={achieved_tps} target={TPS_TARGET} "
        f"sent={final_stress.get('sent')} verdict={'PASS' if send_verdict else 'FAIL'}",
    )
    print(f"{'PASS' if send_verdict else 'FAIL'}: send-side achieved_tps={achieved_tps} "
          f"(target {TPS_TARGET}, >=95% required) - this only proves upstream's own send loop "
          f"wasn't blocked, not that responses kept pace; see the drain check below for that.")

    # A single fixed-timeout test.csv send isn't a fair recovery check on its own - the queues
    # are FIFO, so new traffic gets stuck behind whatever backlog the sustained attack built up
    # (confirmed directly: a shorter 30s burst left a 462-item response_queue_depth/pending_count
    # backlog that drained to 0 within 5s once traffic stopped, so the backlog itself isn't a
    # stall - it just needs draining time proportional to its size). Poll for actual drainage
    # first, THEN confirm ordinary traffic round-trips.
    announce("polling router_1's queues for the backlog to drain", 0, TPS_DRAIN_TIMEOUT_S)
    drain_start = time.time()
    drained = False
    while time.time() - drain_start < TPS_DRAIN_TIMEOUT_S:
        s = stats("router_1") or {}
        g = s.get("gauges", {})
        qd, rqd, pc = g.get("queue_depth"), g.get("response_queue_depth"), g.get("pending_count") or 0
        if qd == 0 and rqd == 0 and pc < 5:
            drained = True
            break
        time.sleep(2)
    drain_elapsed = time.time() - drain_start
    done_waiting(f"backlog drained={drained}", drain_elapsed)
    log.log("router_1", f"post-attack backlog drained={drained} after {drain_elapsed:.1f}s")

    results = send_test_csv("upstream_1")
    recovered = drained and len(results) == 3  # test.csv's 3 ordinary rows
    verdict = "PASS" if recovered else "FAIL"
    log.log(
        "router_1",
        f"post-attack recovery verdict={verdict} rows={len(results)}/3 drained={drained} "
        f"drain_elapsed_s={drain_elapsed:.1f}",
    )
    print(f"{verdict}: post-attack test.csv round-tripped {len(results)}/3 row(s), backlog "
          f"drained={drained} (took {drain_elapsed:.1f}s)")


def scenario_crypto_request_leg_outage_triggers_advice(log):
    """briefs/resilience_v2.md's Round 8 (0120/0130 advice, 0400/0410 - reuses the existing
    0420/0430 wiring for reversal): live-verifies upstream_host's new timeout/advice/reversal
    machinery against the real crypto_host/downstream_host/router stack, complementing the
    isolated StubRouter unit tests (tests/test_advice_reversal.py).

    User's own steer on the trigger: don't kill downstream_host (tears down the whole session
    before a 0100 can even be sent through it - see Round 2 and this round's own write-up) - kill
    crypto_host instead, more realistic (a real STIP trigger is exactly "the HSM/crypto service is
    unreachable, so the network makes its own call"). Not a hard kill either: PAN
    7777777777777777 is configured (simulators/crypto_host/config.json's no_response_pans) to
    hang on validate_0100 specifically, so crypto_host stays healthy for every other PAN and every
    connection stays up throughout - the router just can't finish processing *this* transaction
    for ~10s (CryptoClient's request-leg timeout: 5s + the existing single retry-on-failure),
    well past upstream's own 1.0s advice_timeout_seconds. While validate_0100 hangs, the router
    hasn't registered the transaction in _pending or forwarded it downstream yet - from upstream's
    side this is genuine silence, not a race against a fast decline."""
    print("\n=== SCENARIO: crypto_host unreachable on the request leg - does upstream reverse+advise? ===")
    print(f"    plan: send one 0100 on PAN {REQUEST_LEG_OUTAGE_PAN} (crypto_host hangs on its "
          f"validate_0100) -> poll upstream_1's /logs for up to {REQUEST_LEG_ADVICE_TIMEOUT_S}s "
          f"for 0420+0120 to fire then get acked -> confirm no error_0120_0420.csv entry -> "
          f"recovery check with ordinary test.csv")

    actor = get_actor("upstream_1")
    port = actor["command_port"]
    with open(REQUEST_LEG_OUTAGE_CSV_FILE, "rb") as f:
        requests.post(f"http://127.0.0.1:{port}/upload", files={"file": f}, timeout=5)
    r = requests.get(f"http://127.0.0.1:{port}/start", timeout=5)
    log.log("upstream_1", f"request-leg-outage send status={r.status_code} body={r.text}")
    print(f"upstream_1: send status={r.status_code} body={r.text}")

    # /logs, not the advice_pending_count gauge - the fire-to-ack round trip is fast enough
    # (single-digit milliseconds, when router/downstream are otherwise healthy) that a gauge poll
    # can easily land entirely outside the brief window it's non-zero. /logs captures the actual
    # events instead of racing transient state - same reasoning as
    # scenario_stuck_pending_on_downstream_teardown's own /logs poll above.
    announce("polling upstream_1's /logs for both advice messages to fire and get acked", 0, REQUEST_LEG_ADVICE_TIMEOUT_S)
    poll_start = time.time()
    deadline = poll_start + REQUEST_LEG_ADVICE_TIMEOUT_S
    sent_mtis, acked_mtis = set(), set()
    while time.time() < deadline and not (sent_mtis >= {"0420", "0120"} and acked_mtis >= {"0420", "0120"}):
        try:
            logs = requests.get(f"http://127.0.0.1:{port}/logs", timeout=3).json()
        except requests.RequestException:
            logs = []
        for entry in logs:
            msg = entry.get("message", "")
            if f"pan={REQUEST_LEG_OUTAGE_PAN}" not in msg:
                continue
            for mti in ("0420", "0120"):
                if f"advice: sent {mti}" in msg:
                    sent_mtis.add(mti)
                if msg.startswith(f"advice {mti}") and "acknowledged" in msg:
                    acked_mtis.add(mti)
        time.sleep(0.3)
    saw_fire = sent_mtis == {"0420", "0120"}
    acked = acked_mtis == {"0420", "0120"}
    done_waiting(f"sent={sorted(sent_mtis)} acked={sorted(acked_mtis)}", time.time() - poll_start)
    log.log("upstream_1", f"advice fired={saw_fire} acked={acked} (sent={sorted(sent_mtis)}, acked={sorted(acked_mtis)})")

    error_logged = False
    if os.path.exists(UPSTREAM_ERROR_CSV):
        with open(UPSTREAM_ERROR_CSV, encoding="utf-8-sig") as f:
            error_logged = REQUEST_LEG_OUTAGE_PAN in f.read()

    verdict = "PASS" if (saw_fire and acked and not error_logged) else "FAIL"
    log.log(
        "upstream_1",
        f"request-leg-outage verdict={verdict} fired={saw_fire} acked={acked} "
        f"error_csv_written={error_logged}",
    )
    print(f"{verdict}: 0420+0120 fired={saw_fire}, both acked={acked}, "
          f"error_0120_0420.csv written for this PAN={error_logged} (expected False)")

    results = send_test_csv("upstream_1")
    recovered = len(results) == 3  # test.csv's 3 ordinary rows
    r_verdict = "PASS" if recovered else "FAIL"
    log.log("router_1", f"post-attack recovery verdict={r_verdict} rows={len(results)}/3")
    print(f"{r_verdict}: post-attack test.csv round-tripped {len(results)}/3 row(s)")


def main():
    print(f"[{_now_str()}] test_resilience.py starting - 7 scenarios, roughly 9-10 minutes total.")
    print("  1. upstream failover           (~100s: 2 fixed waits of 35s each, plus two ~15-30s recoveries)")
    print("  2. downstream_host failure     (~50s: 15s + 20s fixed waits, plus one ~15-30s recovery)")
    print("  3. stuck pending on teardown   (~60s: ~15s hang + up to 10s poll + 20s fixed wait + recovery)")
    print("  4. crypto_host failure         (~65s: one ~15-30s send + a 35s fixed breaker-cooldown wait)")
    print("  5. crypto response no-reply queue buildup (~205s: a 180s sustained-attack poll + recovery)")
    print("  6. crypto response fire-and-forget sustains TPS (~85s: a 60s sustained 10%-failure poll + recovery)")
    print("  7. crypto request-leg outage triggers advice/reversal (~30s: up to 20s poll + recovery)")
    print("Every individual wait below is announced first with an expected min/max duration, and")
    print("confirmed done afterward - nothing here is a silent gap.")
    suite_start = time.time()
    log = CsvLog(RESULT_CSV)
    try:
        scenario_upstream_failover(log)
        scenario_downstream_failure(log)
        scenario_stuck_pending_on_downstream_teardown(log)
        scenario_crypto_host_failure(log)
        scenario_crypto_response_no_reply_queue_buildup(log)
        scenario_crypto_response_fire_and_forget_sustains_tps(log)
        scenario_crypto_request_leg_outage_triggers_advice(log)
    finally:
        teardown()
    print(f"\n[{_now_str()}] test_resilience.py finished (took {time.time() - suite_start:.0f}s total)")


if __name__ == "__main__":
    main()

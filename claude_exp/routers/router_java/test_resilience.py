#!/usr/bin/env python3
"""Resilience test suite - see routers/resilience.md. Direct port of router_py/test_resilience.py;
router_java's monitor.main actor-lifecycle helpers (get_actor/is_running/launch_actor/stop_actor/
wait_for_ready) match router_py's signatures exactly (is_running/wait_for_ready both take the same
shapes), and router_java's actor names (router_1/router_2/upstream_1/upstream_2/crypto_host/
downstream_host - upstream_1 comes from the shared upstream_host component's own config.json)
match router_py's 1:1, so this port only differs in the module-level bookkeeping (CSV path,
imports) - see routers/to_do_java_cpp.md for the port tracking, and router_cpp/test_resilience.py
for the *other* port, which needed real actor-name/signature adjustments router_java didn't.

Orchestrated in Python (not bash), because this suite needs to kill and restart individual actors
mid-run and poll their /stats between transitions - all process-lifecycle logic here is reused
directly from monitor/main.py (discover_actors/launch_actor/stop_actor/is_running/wait_for_ready)
rather than reimplemented, since that module already solves "spawn/kill one named actor and know
when it's really ready" for the monitor UI. Every non-upstream_host/downstream_host actor here is
launched via `docker exec -d` into router_java's already-built-and-running container
(`./start.sh`) - unlike router_py's plain host subprocesses, so the container must already be up
before running this.

Both upstream_1 and upstream_2 (and their routers, router_1/router_2) are brought up regardless of
their config.json `is_active` flag - the whole point of this suite is exercising the two-upstream
topology, not the single-upstream default used elsewhere.

Usage: python3 test_resilience.py
Output: console narration of each transition, plus routers/router_java/test_resilience.csv
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
RESULT_CSV = os.path.join(PROJECT_ROOT, "test_resilience.csv")

# Default CryptoClient breaker settings (RouterConfig.java/CryptoClient.java) - not overridden by
# any router_1/router_2 config.json in this repo, so these constants match production behavior.
# Same values as router_py's - both languages' defaults are 30s.
BREAKER_COOLDOWN_S = 30
PING_INTERVAL_S = 30  # shared upstream_host's config.json ping_0800_seconds

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
    the session teardown that follows (Dispatcher.java's drainAndStop, once the downstream
    receiver thread's recv() notices downstream_host is gone) reports the abandoned
    transaction(s) instead of silently dropping them - the same gap router_py found and fixed
    building Phase 3 of the debug-tracing tooling (briefs/old/debug_trace_master.md), later ported
    here (see routers/to_do_java_cpp.md's "Done" section)."""
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
    print(f"{verdict}: session teardown logged the abandoned transaction (Dispatcher.java drainAndStop)")

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


def main():
    print(f"[{_now_str()}] test_resilience.py starting - 4 scenarios, roughly 4-5 minutes total.")
    print("  1. upstream failover           (~100s: 2 fixed waits of 35s each, plus two ~15-30s recoveries)")
    print("  2. downstream_host failure     (~50s: 15s + 20s fixed waits, plus one ~15-30s recovery)")
    print("  3. stuck pending on teardown   (~60s: ~15s hang + up to 10s poll + 20s fixed wait + recovery)")
    print("  4. crypto_host failure         (~65s: one ~15-30s send + a 35s fixed breaker-cooldown wait)")
    print("Every individual wait below is announced first with an expected min/max duration, and")
    print("confirmed done afterward - nothing here is a silent gap.")
    print("Prerequisite: router_java's Docker container must already be running (./start.sh).")
    suite_start = time.time()
    log = CsvLog(RESULT_CSV)
    try:
        scenario_upstream_failover(log)
        scenario_downstream_failure(log)
        scenario_stuck_pending_on_downstream_teardown(log)
        scenario_crypto_host_failure(log)
    finally:
        teardown()
    print(f"\n[{_now_str()}] test_resilience.py finished (took {time.time() - suite_start:.0f}s total)")


if __name__ == "__main__":
    main()

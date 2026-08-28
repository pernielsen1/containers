#!/usr/bin/env python3
"""briefs/resilience_v2.md ("OK let's make resilience_soak.sh scripts" -> run_soak_resilience_hard.sh):
sustained TPS traffic against the full local host-python stack, hard-killing crypto_host (a real
SIGKILL - see chaos_monkey.py's hard_kill_actor, "a real crash / abruptly severed connection, not
a clean shutdown") after a fixed 1 minute of healthy traffic, holding it dead for
--crypto_fail_minutes, then restarting it - all while traffic keeps flowing throughout.

brief's own framing: "this will trigger a bunch of 0120 and 0420 messages - interesting if we can
keep up". Traced against what's actually built (resilience.md Round 8): 0120/0420 fire when a full
0100->0110 round trip exceeds upstream_host's advice_timeout_seconds (1.0s production default) -
NOT merely "crypto_host is unreachable". router/dispatcher.py's crypto call degrades gracefully on
failure (unenriched f47, forwards anyway - see chaos_slow.py's Round 5 finding, "transactions keep
round-tripping ... once CryptoClient's breaker opens"), and a killed process refuses new
connections almost instantly (TCP RST, not a hang) - so a genuine >1s round trip during the outage
is NOT a given the way it was for Round 8's request-leg PAN hang. This script doesn't assume
either way; it measures during_kill's own achieved_tps/latency same as the other two stages and
reports how many 0120/0420 advice lines actually appear in router_1's /logs, so the brief's own
open question gets answered from what actually happens, not from what was expected.

Three separate stress windows (before_kill / during_kill / after_kill), not one continuous
--duration covering the whole run: upstream_1's /start resets its counters (sent, latencies,
results) every call (see upstream_host/main.py), so three back-to-back windows each yield a full,
independent /stress_stats row (real p50/p90/p95/p99, not a bucketed approximation) - exactly the
per-stage breakdown the brief asks for ("numbers before the kill, during the kill and after the
kill"), reusing the same stress_stats shape stress_run.sh's own row uses rather than inventing a
windowed-percentile feature. The short gap between windows (a few seconds, while this script
issues the next /start and confirms it's accepted) means total wall-clock traffic isn't
perfectly continuous across stage boundaries - immaterial for a soak measuring sustained
throughput per stage, not investigating sub-second gaps.

Usage: python3 soak_resilience_hard.py [minutes] [crypto_fail_minutes]
  minutes               total soak duration, in minutes (default 10). Must be large enough for a
                         1-minute before_kill stage + crypto_fail_minutes + a >=30s after_kill
                         stage, or this exits early with an error.
  crypto_fail_minutes    how long crypto_host stays dead (default 2)
Output: console narration plus THREE rows in routers/csv_results/soak_results.csv +
soak_summary.csv, implementation="router_py_before_kill" / "router_py_during_kill" /
"router_py_after_kill".
Prerequisite: none of the actors need to be running yet - starts the full local stack itself.
Does NOT touch the shared routers/crypto_host container.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import monitor.main as monitor  # noqa: E402
from test_resilience import (  # noqa: E402
    CSV_FILE,
    _now_str,
    announce,
    done_waiting,
    get_actor,
    is_running,
    launch_actor,
    narrated_sleep,
    send_test_csv,
    stats,
    stress_stats,
    wait_for_ready,
)
from soak_result_csv import record_result  # noqa: E402

import requests  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
TPS_TARGET = 100
POLL_INTERVAL_S = 10
GRACE_S = 5
BEFORE_KILL_S = 60  # fixed per the brief: "after 1 minute the crypto_host is killed"
MIN_AFTER_KILL_S = 30

launched = []  # actors this script itself started - only these get torn down at the end


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


def hard_kill_actor(name):
    """SIGKILL, not a graceful POST /stop - see chaos_monkey.py's hard_kill_actor, same
    rationale reused here rather than duplicated: a real crash is a materially different failure
    mode (no FIN, peer socket just goes dead / connection refused on the next attempt) than a
    clean shutdown."""
    actor = get_actor(name)
    with monitor._processes_lock:
        proc = monitor._processes.get(name)
    if proc is None:
        monitor.stop_actor(actor)
        return
    proc.kill()
    proc.wait(timeout=5)
    with monitor._processes_lock:
        if monitor._processes.get(name) is proc:
            del monitor._processes[name]
    if actor in launched:
        launched.remove(actor)


def teardown():
    while launched:
        actor = launched.pop()
        try:
            monitor.stop_actor(actor)
            print(f"[teardown] stopped {actor['name']}")
        except Exception as e:
            print(f"[teardown] failed to stop {actor['name']}: {e}")


def count_advice_log_lines():
    """Counts 0120/0420-related lines currently in router_1's own /logs ring buffer (bounded,
    2000 lines - see shared/log_buffer.py) - purely informational context for whether this
    particular hard-kill stage actually triggered any store-and-forward advice traffic, per this
    script's own module docstring on why that's an open question rather than a given."""
    r = stats("router_1")  # not used for its return value - just confirms router_1 answers first
    if r is None:
        return None
    try:
        resp = requests.get("http://127.0.0.1:8080/logs", params={"format": "text"}, timeout=3)
        resp.raise_for_status()
        return sum(1 for line in resp.text.splitlines() if "0120" in line or "0420" in line)
    except requests.RequestException:
        return None


def run_stress_window(label, duration_s, tps=TPS_TARGET, warmup_s=0):
    """Uploads test.csv and drives one independent /start...duration window, polling every
    POLL_INTERVAL_S, then returns upstream_1's final /stress_stats dict for that window alone -
    /start resets sent/latencies/results each call (see this file's module docstring)."""
    print(f"\n=== STAGE: {label} ({duration_s}s @ {tps} TPS) ===")
    actor = get_actor("upstream_1")
    port = actor["command_port"]
    with open(CSV_FILE, "rb") as f:
        requests.post(f"http://127.0.0.1:{port}/upload", files={"file": f}, timeout=5)
    r = requests.get(
        f"http://127.0.0.1:{port}/start",
        params={"rate": tps, "duration": duration_s, "warmup_s": warmup_s},
        timeout=5,
    )
    print(f"upstream_1: stress start status={r.status_code} body={r.text}")

    deadline = time.time() + warmup_s + 2 + duration_s
    while time.time() < deadline:
        time.sleep(min(POLL_INTERVAL_S, max(0.0, deadline - time.time())))
        r_stats = stats("router_1") or {}
        u_stats = stress_stats("upstream_1") or {}
        conns = r_stats.get("connections", {})
        gauges = r_stats.get("gauges", {})
        print(
            f"[{_now_str()}] router_1: connections={conns} queue_depth={gauges.get('queue_depth')} "
            f"response_queue_depth={gauges.get('response_queue_depth')} "
            f"advice_queue_depth={gauges.get('advice_queue_depth')} "
            f"advice_response_queue_depth={gauges.get('advice_response_queue_depth')} "
            f"pending_count={gauges.get('pending_count')} | upstream_1: "
            f"achieved_tps={u_stats.get('achieved_tps')} sent={u_stats.get('sent')} "
            f"received={u_stats.get('received')} errors={u_stats.get('errors')}"
        )

    narrated_sleep(GRACE_S, f"{label}: letting the window's tail settle before reading final stats")
    final = stress_stats("upstream_1") or {}
    print(f"{label}: sent={final.get('sent')} received={final.get('received')} "
          f"errors={final.get('errors')} achieved_tps={final.get('achieved_tps')}")
    return final


def record_stage(label, duration_s, final):
    row = (
        f"router_py_{label};{TPS_TARGET};{duration_s};{final.get('sent', 0)};"
        f"{final.get('received', 0)};{final.get('errors', 0)};{final.get('achieved_tps', 0)};"
        f"{final.get('p50_ms', 0)};{final.get('p90_ms', 0)};{final.get('p95_ms', 0)};"
        f"{final.get('p99_ms', 0)};{final.get('max_ms', 0)}"
    )
    record_result(row)


def main():
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 10
    crypto_fail_minutes = float(sys.argv[2]) if len(sys.argv) > 2 else 2
    during_kill_s = int(crypto_fail_minutes * 60)
    total_s = int(minutes * 60)
    after_kill_s = total_s - BEFORE_KILL_S - during_kill_s
    if after_kill_s < MIN_AFTER_KILL_S:
        print(
            f"ERROR: {minutes:.1f} min total isn't enough for a {BEFORE_KILL_S}s before_kill "
            f"stage + {during_kill_s}s during_kill (--crypto_fail_minutes={crypto_fail_minutes}) "
            f"+ a >={MIN_AFTER_KILL_S}s after_kill stage. Increase minutes or lower "
            f"crypto_fail_minutes.", file=sys.stderr,
        )
        sys.exit(1)

    print(f"[{_now_str()}] soak_resilience_hard.py starting - {minutes:.0f} min total: "
          f"{BEFORE_KILL_S}s before_kill, {during_kill_s}s during_kill "
          f"(crypto_fail_minutes={crypto_fail_minutes}), {after_kill_s}s after_kill.")
    print("  Every wait below is announced first with an expected min/max duration, and confirmed")
    print("  done afterward - nothing here is a silent gap.")

    try:
        for name in ["crypto_host", "downstream_host", "router_1", "upstream_1"]:
            start_actor(name)
        narrated_sleep(2, "letting the topology settle before sustained traffic")

        before_advice = count_advice_log_lines()
        before_final = run_stress_window("before_kill", BEFORE_KILL_S, warmup_s=10)
        record_stage("before_kill", BEFORE_KILL_S, before_final)

        print("\n=== hard-killing crypto_host ===")
        hard_kill_actor("crypto_host")

        during_final = run_stress_window("during_kill", during_kill_s)
        record_stage("during_kill", during_kill_s, during_final)
        during_advice = count_advice_log_lines()

        print("\n=== restarting crypto_host ===")
        start_actor("crypto_host")

        after_final = run_stress_window("after_kill", after_kill_s)
        record_stage("after_kill", after_kill_s, after_final)
        after_advice = count_advice_log_lines()

        results = send_test_csv("upstream_1")
        recovered = len(results) == 3
        print(f"\n{'PASS' if recovered else 'FAIL'}: post-recovery test.csv round-tripped "
              f"{len(results)}/3 row(s)")

        print(
            f"\n0120/0420 advice log-line counts (router_1's /logs, cumulative - see "
            f"count_advice_log_lines docstring): before_kill={before_advice} "
            f"during_kill={during_advice} after_kill={after_advice}"
        )

        overall_ok = (
            recovered
            and (before_final.get("achieved_tps") or 0) >= TPS_TARGET * 0.95
            and (after_final.get("achieved_tps") or 0) >= TPS_TARGET * 0.95
        )
        print(f"\n[{_now_str()}] soak_resilience_hard.py finished: "
              f"{'PASS' if overall_ok else 'FAIL'}")
    finally:
        teardown()

    if not overall_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()

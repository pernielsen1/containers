#!/usr/bin/env python3
"""briefs/resilience_v2.md ("OK let's make resilience_soak.sh scripts" -> run_soak_resilience_light.sh):
sustained TPS traffic against the full local host-python stack (downstream_host, router_1,
upstream_1, and this repo's own crypto_host stub - simulators/crypto_host/main.py, NOT the shared
OpenSSL-backed routers/crypto_host container run_soak.sh/stress_run.sh use for cross-implementation
perf comparisons) while a flat --fail_percentage of crypto_host's requests (any PAN, any leg) get
no response at all.

This is the soak-scale version of test_resilience.py's scenario_crypto_response_fire_and_forget_
sustains_tps (Round 7, resilience.md) - that scenario proved the *mechanism* (router/session.py's
short response-leg CryptoClient timeout keeps 100 TPS met even with a bad-card mix); this script
runs the same idea for an arbitrary duration/percentage as a proper soak, with results landing in
the same csv_results/soak_results.csv + soak_summary.csv run_soak.sh writes to (implementation
column suffixed "_fail_pctN" so a resilience run is never confused with an ordinary clean-run
row) rather than a one-off pytest-style pass/fail.

Percentage is applied inside crypto_host itself (see simulators/crypto_host/main.py's
fail_percentage chaos hook), not via a pre-baked bad-card CSV mix like Round 7's
tps_10pct_bad_card.csv - a runtime percentage means this script can be pointed at any
--fail_percentage without needing a matching CSV checked in for each value, and it applies to
ordinary test.csv traffic rather than needing its own card mix.

Usage: python3 soak_resilience_light.py [minutes] [fail_percentage] [tps]
  minutes         duration of the sustained-traffic window, in minutes (default 10)
  fail_percentage percent (0-100) of crypto_host requests that get no response (default 10)
  tps             target transactions/sec (default 100)
Output: console narration (same announce/done_waiting style as test_resilience.py) plus a row in
routers/csv_results/soak_results.csv + soak_summary.csv (implementation="router_py_fail_pctN").
Prerequisite: none of the actors need to be running yet - starts the full local stack itself, the
same way test_resilience.py/chaos_monkey.py do. Does NOT touch the shared routers/crypto_host
container - safe to run alongside/independent of run_soak.sh.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import monitor.main as monitor  # noqa: E402
from test_resilience import (  # noqa: E402
    CSV_FILE,
    UPSTREAM_ERROR_CSV,
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
POLL_INTERVAL_S = 10
WARMUP_S = 10
GRACE_S = 5
DRAIN_TIMEOUT_S = 60

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


def start_crypto_host_with_fail_percentage(fail_percentage, timeout=15):
    """crypto_host isn't in monitor.CONFIG_REQUIRED_TYPES (it always uses its own default
    config.json path - see monitor/main.py), so launch_actor() has no way to pass it an extra
    CLI flag. Builds the Popen directly instead, but registers it in monitor's own _processes
    dict so stop_actor()/is_running() (used by teardown() and every other helper here) keep
    working exactly as if launch_actor() had started it."""
    actor = monitor.get_actor("crypto_host")
    if monitor.is_running("crypto_host"):
        # A stray already-running instance would be using whatever fail_percentage IT was
        # started with (likely 0) - restart it under our control so the flag actually applies.
        monitor.stop_actor(actor)
    script = os.path.join(monitor.PROJECT_ROOT, monitor.SCRIPTS_BY_TYPE["crypto"])
    cmd = [sys.executable, script, "--fail-percentage", str(fail_percentage)]
    proc = subprocess.Popen(cmd, cwd=monitor.PROJECT_ROOT)
    with monitor._processes_lock:
        monitor._processes["crypto_host"] = proc
    launched.append(actor)
    announce("waiting for crypto_host to become ready", 0, timeout)
    start = time.time()
    monitor.wait_for_ready(actor, timeout=timeout)
    done_waiting("crypto_host ready", time.time() - start)
    return actor


def teardown():
    while launched:
        actor = launched.pop()
        try:
            monitor.stop_actor(actor)
            print(f"[teardown] stopped {actor['name']}")
        except Exception as e:
            print(f"[teardown] failed to stop {actor['name']}: {e}")


def main():
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 10
    fail_percentage = float(sys.argv[2]) if len(sys.argv) > 2 else 10
    tps_target = float(sys.argv[3]) if len(sys.argv) > 3 else 100
    duration_s = int(minutes * 60)

    print(f"[{_now_str()}] soak_resilience_light.py starting - {minutes:.0f} min "
          f"({duration_s}s) at {tps_target} TPS, fail_percentage={fail_percentage}%.")
    print("  Every wait below is announced first with an expected min/max duration, and confirmed")
    print("  done afterward - nothing here is a silent gap.")

    try:
        start_crypto_host_with_fail_percentage(fail_percentage)
        for name in ["downstream_host", "router_1", "upstream_1"]:
            start_actor(name)
        narrated_sleep(2, "letting the topology settle before sustained traffic")

        actor = get_actor("upstream_1")
        port = actor["command_port"]
        with open(CSV_FILE, "rb") as f:
            requests.post(f"http://127.0.0.1:{port}/upload", files={"file": f}, timeout=5)
        r = requests.get(
            f"http://127.0.0.1:{port}/start",
            params={"rate": tps_target, "duration": duration_s, "warmup_s": WARMUP_S},
            timeout=5,
        )
        print(f"upstream_1: stress start status={r.status_code} body={r.text}")

        deadline = time.time() + WARMUP_S + 2 + duration_s
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

        narrated_sleep(GRACE_S, "letting the run's tail settle before reading final stats")
        final = stress_stats("upstream_1") or {}
        achieved_tps = final.get("achieved_tps") or 0
        send_verdict = achieved_tps >= tps_target * 0.95
        print(f"{'PASS' if send_verdict else 'FAIL'}: send-side achieved_tps={achieved_tps} "
              f"(target {tps_target}, >=95% required)")

        announce("polling router_1's queues for the backlog to drain", 0, DRAIN_TIMEOUT_S)
        drain_start = time.time()
        drained = False
        while time.time() - drain_start < DRAIN_TIMEOUT_S:
            s = stats("router_1") or {}
            g = s.get("gauges", {})
            qd = g.get("queue_depth")
            rqd = g.get("response_queue_depth")
            pc = g.get("pending_count") or 0
            if qd == 0 and rqd == 0 and pc < 5:
                drained = True
                break
            time.sleep(2)
        done_waiting(f"backlog drained={drained}", time.time() - drain_start)

        results = send_test_csv("upstream_1")
        recovered = drained and len(results) == 3
        print(f"{'PASS' if recovered else 'FAIL'}: post-attack test.csv round-tripped "
              f"{len(results)}/3 row(s), backlog drained={drained}")

        error_rows = 0
        if os.path.exists(UPSTREAM_ERROR_CSV):
            with open(UPSTREAM_ERROR_CSV, encoding="utf-8-sig") as f:
                error_rows = max(0, sum(1 for _ in f) - 1)
        print(f"advice-exhausted rows in error_0120_0420.csv: {error_rows} "
              "(0100/0110 fire-and-forget shouldn't trigger 0120/0420 advice traffic at all - "
              "that's downstream-outage/timeout territory, not a slow crypto response leg)")

        tps_suffix = "" if tps_target == 100 else f"_tps{int(tps_target)}"
        impl_label = f"router_py_fail_pct{int(fail_percentage)}{tps_suffix}"
        row = (
            f"{impl_label};{tps_target};{duration_s};{final.get('sent', 0)};"
            f"{final.get('received', 0)};{final.get('errors', 0)};{achieved_tps};"
            f"{final.get('p50_ms', 0)};{final.get('p90_ms', 0)};{final.get('p95_ms', 0)};"
            f"{final.get('p99_ms', 0)};{final.get('max_ms', 0)}"
        )
        record_result(row)
        overall = "PASS" if (send_verdict and recovered) else "FAIL"
        print(f"\n[{_now_str()}] soak_resilience_light.py finished: {overall}")
    finally:
        teardown()

    if overall != "PASS":
        sys.exit(1)


if __name__ == "__main__":
    main()

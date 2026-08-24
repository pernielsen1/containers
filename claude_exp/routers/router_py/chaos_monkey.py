#!/usr/bin/env python3
"""Destructive chaos-monkey script - see briefs/resilience_v2.md ("BE BAD AND DESTRUCTIVE - code
monkeys") and resilience.md's Round 3.

Unlike test_resilience.py's four fixed, scripted scenarios (which stop actors gracefully via
POST /stop), this repeatedly picks a random actor and SIGKILLs it - a real crash / abruptly
severed connection, not a clean shutdown - waits a random amount of time, restarts it, and checks
that the router gets itself back on track: "a router may lose an upstream or downstream connection
but always needs to be able to recover and be ready for new connections" (resilience_v2.md).

Reuses test_resilience.py's I/O helpers (CsvLog, announce/narrated_sleep, send_test_csv, stats)
rather than duplicating them - only the actor-lifecycle wrapper here differs (hard SIGKILL instead
of the graceful stop test_resilience.py's kill_actor uses).

Cert-desync is deliberately NOT one of the attack types yet - see resilience.md's Round 3 TODO:
each leg already uses its own independent cert/CA pair by design, so simulating a *realistic*
desync (one leg's own cert regenerated without updating its peer) needs more thought than a random
kill-and-restart attack, and got carved out rather than block the rest of this script.

Usage: ./chaos_monkey.sh [rounds] [min_down_s] [max_down_s]   (or: python3 chaos_monkey.py ...)
  rounds       number of attack rounds to run (default 10)
  min_down_s   minimum seconds the killed actor stays down (default 3)
  max_down_s   maximum seconds the killed actor stays down (default 15)
Output: console narration per round, plus router_py/chaos_monkey.csv (timestamp;round;target;event).
Prerequisite: none of the actors need to be running yet - this script starts the full topology
itself, the same way test_resilience.py does.
"""
import csv
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import monitor.main as monitor  # noqa: E402
from test_resilience import (  # noqa: E402
    CSV_FILE,
    CsvLog,
    _now_str,
    announce,
    done_waiting,
    narrated_sleep,
    send_test_csv,
    stats,
)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
RESULT_CSV = os.path.join(PROJECT_ROOT, "chaos_monkey.csv")

TARGETS = ["crypto_host", "downstream_host", "router_1", "upstream_1"]
RECONNECT_TIMEOUT_S = 30  # generous margin over reestablish_seconds=10 + jitter

with open(CSV_FILE, encoding="utf-8-sig") as f:
    EXPECTED_ROWS = sum(1 for _ in csv.reader(f, delimiter=";")) - 1  # minus header

launched = []  # actors this script itself started - only these get torn down at the end


def start_actor(name, timeout=15):
    actor = monitor.get_actor(name)
    if actor is None:
        raise RuntimeError(f"unknown actor: {name}")
    if not monitor.is_running(name):
        monitor.launch_actor(actor)
        launched.append(actor)
    announce(f"waiting for {name} to become ready", 0, timeout)
    start = time.time()
    monitor.wait_for_ready(actor, timeout=timeout)
    done_waiting(f"{name} ready", time.time() - start)
    return actor


def hard_kill_actor(name):
    """SIGKILL, not test_resilience.py's graceful POST /stop - simulates an actual crash rather
    than a clean shutdown, which is a materially different failure mode for the reconnect logic
    to handle (no FIN, the peer's socket just goes dead)."""
    actor = monitor.get_actor(name)
    with monitor._processes_lock:
        proc = monitor._processes.get(name)
    if proc is None:
        # Not tracked as a subprocess by this monitor - shouldn't happen since we launch every
        # actor ourselves at startup, but fall back to the graceful path rather than doing nothing.
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


def wait_for_router_reconnect(timeout=RECONNECT_TIMEOUT_S):
    """Polls router_1's own /stats rather than assuming a fixed reestablish_seconds wait is
    enough - both legs (upstream and downstream) need to show connected, since either one could
    be the leg that was actually attacked (or the other leg's own actor, e.g. upstream_1, being
    the one just restarted)."""
    announce("waiting for router_1 to show both legs connected", 0, timeout)
    start = time.time()
    deadline = start + timeout
    while time.time() < deadline:
        r_stats = stats("router_1")
        if r_stats:
            conns = r_stats.get("connections", {})
            if conns.get("downstream") and conns.get("upstream"):
                done_waiting("router_1 both legs connected", time.time() - start)
                return True
        time.sleep(1)
    done_waiting("router_1 reconnect timed out", time.time() - start)
    return False


def run_round(n, log, min_down_s, max_down_s):
    target = random.choice(TARGETS)
    print(f"\n=== ROUND {n}: hard-kill {target} ===")
    round_start = time.time()

    hard_kill_actor(target)
    log.log(target, "hard_killed")

    down_s = random.uniform(min_down_s, max_down_s)
    narrated_sleep(down_s, f"{target} down - letting the outage actually bite before restarting it")

    start_actor(target)
    log.log(target, "restarted")

    reconnected = wait_for_router_reconnect()
    log.log("router_1", f"reconnected={reconnected}")

    results = send_test_csv("upstream_1")
    recovered = reconnected and len(results) == EXPECTED_ROWS
    verdict = "PASS" if recovered else "FAIL"
    elapsed = time.time() - round_start
    log.log(target, f"recovery verdict={verdict} rows={len(results)}/{EXPECTED_ROWS} elapsed_s={elapsed:.1f}")
    print(f"{verdict}: round {n} ({target}) - {len(results)}/{EXPECTED_ROWS} row(s) round-tripped, "
          f"reconnected={reconnected}, took {elapsed:.1f}s total")
    return target, recovered


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    min_down_s = float(sys.argv[2]) if len(sys.argv) > 2 else 3
    max_down_s = float(sys.argv[3]) if len(sys.argv) > 3 else 15

    print(f"[{_now_str()}] chaos_monkey.py starting - {rounds} round(s), "
          f"down-time {min_down_s:.0f}-{max_down_s:.0f}s per round.")
    print("  Every wait below is announced first with an expected min/max duration, and confirmed")
    print("  done afterward - nothing here is a silent gap.")
    log = CsvLog(RESULT_CSV)
    suite_start = time.time()
    outcomes = []

    try:
        for name in ["crypto_host", "downstream_host", "router_1", "upstream_1"]:
            start_actor(name)
            log.log(name, "up")
        narrated_sleep(2, "letting the topology settle before the first attack")

        for n in range(1, rounds + 1):
            outcomes.append(run_round(n, log, min_down_s, max_down_s))
    finally:
        teardown()

    passed = sum(1 for _, ok in outcomes if ok)
    print(f"\n[{_now_str()}] chaos_monkey.py finished (took {time.time() - suite_start:.0f}s total)")
    print(f"  {passed}/{len(outcomes)} round(s) recovered cleanly")
    by_target = {}
    for target, ok in outcomes:
        counts = by_target.setdefault(target, [0, 0])
        counts[0 if ok else 1] += 1
    for target, (ok_count, fail_count) in sorted(by_target.items()):
        print(f"    {target}: {ok_count} pass, {fail_count} fail")

    if passed < len(outcomes):
        sys.exit(1)


if __name__ == "__main__":
    main()

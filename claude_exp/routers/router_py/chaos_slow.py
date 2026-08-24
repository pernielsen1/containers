#!/usr/bin/env python3
"""Slow chaos scenarios - long, realistic outages that chaos_monkey.py's quick random kills
(3-15s down-time per round) don't exercise. Two fixed scenarios, run back to back:

  1. downstream_host: 10s of smooth running under live traffic, then a hard kill held down for a
     full 2 minutes, then restart - confirming the *normal* reconnect-loop path (there's no
     special "long outage" handling, nor should there need to be) brings router_1 and upstream_1
     back on their own once downstream_host is actually back.
  2. crypto_host: hard-killed and held down for a full 2 minutes while test traffic keeps flowing
     through the router every few seconds - confirming transactions keep round-tripping
     (degraded: unenriched f47, once CryptoClient's breaker opens) rather than stalling, then
     crypto_host comes back and enrichment resumes.

Both scenarios poll router_1's own /stats every POLL_INTERVAL_S while the outage is in progress
and log queue_depth/response_queue_depth/pending_count/connections each time - so what's actually
happening *during* the two minutes is visible in the CSV/console, not just the before/after
recovery check.

Reuses chaos_monkey.py's actor-lifecycle helpers (hard SIGKILL, not test_resilience.py's graceful
POST /stop - see chaos_monkey.py's own docstring for why) and test_resilience.py's I/O helpers,
rather than duplicating either.

Usage: python3 chaos_slow.py
Output: console narration (every wait announced first, confirmed done after - see
test_resilience.py's announce/done_waiting) plus router_py/chaos_slow.csv
(timestamp;target;event).
Prerequisite: none of the actors need to be running yet - starts the full topology itself.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chaos_monkey import (  # noqa: E402
    EXPECTED_ROWS,
    hard_kill_actor,
    start_actor,
    teardown,
    wait_for_router_reconnect,
)
from test_resilience import (  # noqa: E402
    CsvLog,
    _now_str,
    narrated_sleep,
    send_test_csv,
    stats,
)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
RESULT_CSV = os.path.join(PROJECT_ROOT, "chaos_slow.csv")

DOWNSTREAM_OUTAGE_S = 120
CRYPTO_OUTAGE_S = 120
POLL_INTERVAL_S = 10


def poll_router_during(seconds, log, note, send_traffic=False):
    """Logs router_1's connections/gauges every POLL_INTERVAL_S for the given duration, so an
    outage this long isn't just a silent gap in the console/CSV. When send_traffic is set, also
    sends a fresh test batch each interval - there's otherwise nothing to observe the "does
    traffic keep moving, degraded, instead of stalling" behavior with."""
    deadline = time.time() + seconds
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        step = min(POLL_INTERVAL_S, remaining)
        time.sleep(step)

        s = stats("router_1") or {}
        gauges = s.get("gauges", {})
        conns = s.get("connections", {})
        msg = (
            f"{note}: connections={conns} queue_depth={gauges.get('queue_depth')} "
            f"response_queue_depth={gauges.get('response_queue_depth')} "
            f"pending_count={gauges.get('pending_count')}"
        )
        print(f"[{_now_str()}] {msg}")
        log.log("router_1", msg)

        if send_traffic:
            results = send_test_csv("upstream_1")
            batch_msg = f"mid-outage test batch: {len(results)}/{EXPECTED_ROWS} round-tripped"
            print(f"[{_now_str()}] {batch_msg}")
            log.log("upstream_1", batch_msg)


def scenario_downstream_long_outage(log) -> bool:
    print("\n=== SCENARIO 1: downstream_host - 10s smooth, then a 2-minute outage ===")
    log.log("downstream_host", "scenario start")

    narrated_sleep(10, "letting traffic run smoothly before the attack")
    baseline = send_test_csv("upstream_1")
    print(f"pre-attack sanity check: {len(baseline)}/{EXPECTED_ROWS} round-tripped")
    log.log("downstream_host", f"pre-attack sanity check rows={len(baseline)}/{EXPECTED_ROWS}")

    hard_kill_actor("downstream_host")
    log.log("downstream_host", "hard_killed")

    # No traffic during this outage - upstream_1 has nowhere for it to go until downstream_host
    # (and the session it anchors) is back, so sending would just time out uninformatively. The
    # point here is watching connections drop and *stay* dropped for the full two minutes, then
    # recover on the router's own reconnect loop once downstream_host is actually back.
    poll_router_during(DOWNSTREAM_OUTAGE_S, log, "downstream_host down", send_traffic=False)

    start_actor("downstream_host")
    log.log("downstream_host", "restarted")

    reconnected = wait_for_router_reconnect()
    log.log("router_1", f"reconnected={reconnected}")

    results = send_test_csv("upstream_1")
    recovered = reconnected and len(results) == EXPECTED_ROWS
    verdict = "PASS" if recovered else "FAIL"
    log.log("downstream_host", f"recovery verdict={verdict} rows={len(results)}/{EXPECTED_ROWS}")
    print(f"{verdict}: downstream_host long-outage scenario - {len(results)}/{EXPECTED_ROWS} "
          f"row(s) round-tripped, reconnected={reconnected}")
    return recovered


def scenario_crypto_long_outage(log) -> bool:
    print("\n=== SCENARIO 2: crypto_host - 2-minute outage with traffic kept flowing ===")
    log.log("crypto_host", "scenario start")

    hard_kill_actor("crypto_host")
    log.log("crypto_host", "hard_killed")

    # Unlike downstream_host's outage, the router/upstream_1 link never drops here - only the
    # crypto leg is down - so traffic can (and should) keep moving the whole two minutes,
    # degraded once CryptoClient's breaker opens (unenriched f47) rather than stalling.
    poll_router_during(CRYPTO_OUTAGE_S, log, "crypto_host down", send_traffic=True)

    start_actor("crypto_host")
    log.log("crypto_host", "restarted")

    narrated_sleep(2, "letting crypto_host settle before the recovery check")
    results = send_test_csv("upstream_1")
    recovered = len(results) == EXPECTED_ROWS
    verdict = "PASS" if recovered else "FAIL"
    log.log("crypto_host", f"recovery verdict={verdict} rows={len(results)}/{EXPECTED_ROWS}")
    print(f"{verdict}: crypto_host long-outage scenario - {len(results)}/{EXPECTED_ROWS} "
          f"row(s) round-tripped")
    return recovered


def main():
    print(f"[{_now_str()}] chaos_slow.py starting - two long-outage scenarios "
          f"({DOWNSTREAM_OUTAGE_S}s downstream_host, {CRYPTO_OUTAGE_S}s crypto_host).")
    print("  Every wait below is announced first with an expected duration, and confirmed done")
    print("  afterward - nothing here is a silent gap, including the two-minute outages.")
    log = CsvLog(RESULT_CSV)
    outcomes = []

    try:
        for name in ["crypto_host", "downstream_host", "router_1", "upstream_1"]:
            start_actor(name)
            log.log(name, "up")
        narrated_sleep(2, "letting the topology settle before scenario 1")

        outcomes.append(("downstream_host_long_outage", scenario_downstream_long_outage(log)))
        narrated_sleep(5, "letting things settle between scenarios")
        outcomes.append(("crypto_host_long_outage", scenario_crypto_long_outage(log)))
    finally:
        teardown()

    passed = sum(1 for _, ok in outcomes if ok)
    print(f"\n[{_now_str()}] chaos_slow.py finished")
    print(f"  {passed}/{len(outcomes)} scenario(s) recovered cleanly")
    for name, ok in outcomes:
        print(f"    {name}: {'PASS' if ok else 'FAIL'}")

    if passed < len(outcomes):
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""briefs/resilience_v2.md ("OK let's make resilience_soak.sh scripts" -> run_soak_resilience_hard.sh):
sustained TPS traffic against the full local host-python stack, hard-killing crypto_host (a real
SIGKILL - see chaos_monkey.py's hard_kill_actor, "a real crash / abruptly severed connection, not
a clean shutdown") after a before_kill stage of healthy traffic, holding it dead for
--crypto_fail_minutes, then restarting it - all while traffic keeps flowing throughout. The
brief's original spec fixed before_kill at 1 minute (sized for its 10-minute soak default);
before_kill/during_kill/after_kill are now all fractions of the total `minutes` instead (with
floors - see BEFORE_KILL_FRACTION etc. below), so a short experimental run isn't stuck paying a
10-minute soak's fixed overhead - pass --crypto_fail_minutes explicitly to pin the brief's
original real-world 2-minute value regardless of `minutes`.

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

Usage: python3 soak_resilience_hard.py [minutes] [crypto_fail_minutes] [--stub-crypto]
  minutes               total soak duration, in minutes (default 2 - kept low for fast iteration
                         while experimenting; before_kill/during_kill/after_kill stage lengths
                         are all calculated as fractions of this, with floors below, rather than
                         the fixed 60s/2min/30s the brief's original 10-minute soak used - so a
                         short experimental run doesn't spend its whole budget on stages sized
                         for a 10-minute soak). Must leave at least AFTER_KILL_MIN_S for
                         after_kill once before_kill and during_kill are sized, or this exits
                         early with an error.
  crypto_fail_minutes    how long crypto_host stays dead. Default: a fraction of `minutes` (see
                         DURING_KILL_FRACTION below) rather than a fixed value - pass this
                         explicitly to pin it (e.g. the brief's real-world 2 minutes).
  --stub-crypto          use this scenario's own lightweight Flask-dev-server crypto_host stub
                         instead of the real, shared C++ container (the default - see below). Starts/
                         kills/restarts the stub itself, like this script did before --real-crypto
                         existed. Useful without docker (e.g. this repo's dev sandbox), or to
                         reproduce the stub's own ~140 req/s ceiling (project_resilience_hard_soak.md
                         memory, 2026-08-29) deliberately.
Default (no flag): runs against the real, shared C++ crypto_host container (routers/crypto_host,
port 5099/8099 - the one run_soak.sh/stress_run.sh use) - simplest path for a normal run, and the
container doesn't have the stub's capacity ceiling (confirmed clean at 80 TPS, 2026-08-30). That
container has to already be up (crypto_host/start.sh) - this script only docker-kills/docker-starts
it, it does not build or first-start it. router_1 is pointed at it via
router/router_1/config_perf.json (already used/verified by stress_run.sh's perf runs) instead of the
default config.json.
Output: console narration plus THREE rows in routers/csv_results/soak_results.csv +
soak_summary.csv, implementation="router_py_real_crypto_before_kill" / "..._during_kill" /
"..._after_kill" by default, or "router_py_before_kill" / etc. with --stub-crypto - the two capacity
profiles never land under the same label.
Prerequisite: the real crypto_host container already running (crypto_host/start.sh) - unless
--stub-crypto is passed, in which case none of the actors (including crypto_host) need to be
running yet, this script starts the full local stack itself.
"""
import os
import subprocess
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
# 100, the brief's original target - fine at the default real-crypto-container mode (confirmed
# clean at 80 TPS against it, ~2ms crypto_rtt, 0 errors, 2026-08-30). Only lower this - or pass
# --stub-crypto and lower it to 60 - if running against the local Flask stub, which has a measured
# ~140 req/s ceiling (each transaction needs 2 crypto calls, so 100 TPS demands ~200 req/s, above
# it); see project_resilience_hard_soak.md memory for both numbers.
TPS_TARGET = 100
POLL_INTERVAL_S = 10
GRACE_S = 5
# Stage lengths scale off total `minutes` instead of the brief's fixed 60s/2min/30s (sized for
# its original 10-minute soak) - at a short experimental total those fixed values either eat the
# whole run or don't leave enough of it for after_kill. Floors keep each stage long enough to be
# meaningful (before_kill needs a few TPS-ramp cycles to settle; during_kill needs to clear
# advice_timeout_seconds, 1.0s production default, several times over) even at a tiny `minutes`.
BEFORE_KILL_FRACTION = 0.15
BEFORE_KILL_MIN_S = 15
DURING_KILL_FRACTION = 0.35  # used only when --crypto_fail_minutes isn't passed explicitly
DURING_KILL_MIN_S = 15
AFTER_KILL_MIN_S = 20

# Real-crypto mode (default - see module docstring / --stub-crypto): the real container's command
# API, docker container name (docker-compose.yml's container_name), and the router_1 config that
# points at it instead of the local stub - reusing stress_run.sh's already-verified
# config_perf.json rather than authoring a new one.
REAL_CRYPTO_STATS_URL = "http://127.0.0.1:8099/stats"
REAL_CRYPTO_CONTAINER = "crypto_host"
ROUTER_1_REAL_CRYPTO_CONFIG = os.path.join(PROJECT_ROOT, "router", "router_1", "config_perf.json")

REAL_CRYPTO = True  # default on - see --stub-crypto in main(); read by record_stage() for the CSV label
IMPL_LABEL = "router_py_real_crypto"

launched = []  # actors this script itself started - only these get torn down at the end


def ensure_real_crypto_up():
    """This script doesn't build or first-start the shared container - crypto_host/start.sh is the
    user's own step (docker compose up -d --build, idempotent) - this only checks it's already
    reachable, same check/message run_soak.sh already uses before its own perf runs."""
    try:
        if requests.get(REAL_CRYPTO_STATS_URL, timeout=2).status_code == 200:
            return
    except requests.RequestException:
        pass
    print(
        "ERROR: shared crypto_host (port 8099) is not responding - start it first:\n"
        "  cd crypto_host && ./start.sh",
        file=sys.stderr,
    )
    sys.exit(1)


def docker_kill_crypto_host():
    """SIGKILL via docker, not docker stop - same "real crash, no FIN" rationale as
    hard_kill_actor() above, just against the container instead of a locally-launched process."""
    subprocess.run(["docker", "kill", REAL_CRYPTO_CONTAINER], check=True, capture_output=True)


def docker_start_crypto_host(timeout=15):
    subprocess.run(["docker", "start", REAL_CRYPTO_CONTAINER], check=True, capture_output=True)
    announce("waiting for real crypto_host container to become ready", 0, timeout)
    start = time.time()
    deadline = start + timeout
    while time.time() < deadline:
        try:
            if requests.get(REAL_CRYPTO_STATS_URL, timeout=1).status_code == 200:
                done_waiting("real crypto_host ready", time.time() - start)
                return
        except requests.RequestException:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"real crypto_host did not become ready within {timeout}s of docker start")


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


def reset_crypto_breaker():
    """Tells router_1 crypto_host is back *now*, instead of letting its breaker discover that on
    its own self-renewing cooldown clock (crypto_client.py's CryptoClient.validate() re-arms
    _open_until on every failed probe with no awareness of restarts - see
    project_resilience_hard_soak.md memory's after_kill spillover writeup, 2026-08-30). Called
    right after start_actor("crypto_host") has already confirmed the real service port is open
    (monitor.wait_for_ready's _service_port_open probe) - that confirmation is the "event" this
    is event-driven off of. Best-effort: a stopped router or a request hiccup here just means the
    breaker falls back to its own clock, same as before this existed."""
    actor = get_actor("router_1")
    port = actor["command_port"]
    try:
        requests.post(f"http://127.0.0.1:{port}/crypto/reset_breaker", timeout=3)
    except requests.RequestException as e:
        print(f"  (crypto breaker reset failed, falling back to its own cooldown clock: {e})")


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
        # Rolling (not per-window) p50/max per hop - see shared/stats.py's record_latency -
        # pinpoints WHERE time goes (queue wait for a free worker vs. the crypto/downstream
        # calls themselves) instead of guessing from queue_depth/errors alone.
        latency = r_stats.get("latency", {})

        def hop(name):
            b = latency.get(name)
            return f"{name}=p50:{b['p50_ms']}/max:{b['max_ms']}" if b else f"{name}=n/a"

        print(
            f"[{_now_str()}] router_1: connections={conns} queue_depth={gauges.get('queue_depth')} "
            f"response_queue_depth={gauges.get('response_queue_depth')} "
            f"advice_queue_depth={gauges.get('advice_queue_depth')} "
            f"advice_response_queue_depth={gauges.get('advice_response_queue_depth')} "
            f"pending_count={gauges.get('pending_count')} | hops(ms): {hop('queue_wait')} "
            f"{hop('crypto_rtt')} {hop('downstream_rtt')} {hop('total')} | upstream_1: "
            f"achieved_tps={u_stats.get('achieved_tps')} sent={u_stats.get('sent')} "
            f"received={u_stats.get('received')} errors={u_stats.get('errors')} | advice: "
            f"0120 sent={u_stats.get('advice_0120_sent')}/acked={u_stats.get('advice_0120_acked')} "
            f"0420 sent={u_stats.get('advice_0420_sent')}/acked={u_stats.get('advice_0420_acked')}"
        )

    narrated_sleep(GRACE_S, f"{label}: letting the window's tail settle before reading final stats")
    final = stress_stats("upstream_1") or {}
    print(f"{label}: sent={final.get('sent')} received={final.get('received')} "
          f"errors={final.get('errors')} achieved_tps={final.get('achieved_tps')} | advice: "
          f"0120 sent={final.get('advice_0120_sent')}/acked={final.get('advice_0120_acked')} "
          f"0420 sent={final.get('advice_0420_sent')}/acked={final.get('advice_0420_acked')}")
    return final


def record_stage(label, duration_s, final):
    row = (
        f"{IMPL_LABEL}_{label};{TPS_TARGET};{duration_s};{final.get('sent', 0)};"
        f"{final.get('received', 0)};{final.get('errors', 0)};{final.get('achieved_tps', 0)};"
        f"{final.get('p50_ms', 0)};{final.get('p90_ms', 0)};{final.get('p95_ms', 0)};"
        f"{final.get('p99_ms', 0)};{final.get('max_ms', 0)};{final.get('advice_0120_sent', 0)};"
        f"{final.get('advice_0120_acked', 0)};{final.get('advice_0420_sent', 0)};"
        f"{final.get('advice_0420_acked', 0)}"
    )
    record_result(row)


def main():
    global REAL_CRYPTO, IMPL_LABEL
    args = sys.argv[1:]
    if "--stub-crypto" in args:
        args = [a for a in args if a != "--stub-crypto"]
        REAL_CRYPTO = False
        IMPL_LABEL = "router_py"

    minutes = float(args[0]) if len(args) > 0 else 2
    crypto_fail_arg = args[1] if len(args) > 1 else ""
    explicit_crypto_fail = crypto_fail_arg.strip() != ""

    total_s = int(minutes * 60)
    before_kill_s = max(BEFORE_KILL_MIN_S, round(total_s * BEFORE_KILL_FRACTION))
    if explicit_crypto_fail:
        crypto_fail_minutes = float(crypto_fail_arg)
        during_kill_s = int(crypto_fail_minutes * 60)
    else:
        during_kill_s = max(DURING_KILL_MIN_S, round(total_s * DURING_KILL_FRACTION))
        crypto_fail_minutes = during_kill_s / 60
    after_kill_s = total_s - before_kill_s - during_kill_s
    if after_kill_s < AFTER_KILL_MIN_S:
        print(
            f"ERROR: {minutes:.1f} min total isn't enough for a {before_kill_s}s before_kill "
            f"stage + {during_kill_s}s during_kill (crypto_fail_minutes={crypto_fail_minutes:.2f}"
            f"{'' if explicit_crypto_fail else ', auto'}) + a >={AFTER_KILL_MIN_S}s after_kill "
            f"stage. Increase minutes or lower --crypto_fail_minutes.", file=sys.stderr,
        )
        sys.exit(1)

    print(f"[{_now_str()}] soak_resilience_hard.py starting - {minutes:.1f} min total: "
          f"{before_kill_s}s before_kill, {during_kill_s}s during_kill "
          f"(crypto_fail_minutes={crypto_fail_minutes:.2f}"
          f"{'' if explicit_crypto_fail else ', auto'}), {after_kill_s}s after_kill.")
    print("  Every wait below is announced first with an expected min/max duration, and confirmed")
    print("  done afterward - nothing here is a silent gap.")

    try:
        if REAL_CRYPTO:
            ensure_real_crypto_up()
            print(f"[{_now_str()}] using the real, shared crypto_host container (port 5099/8099) "
                  f"- router_1 pointed at it via {ROUTER_1_REAL_CRYPTO_CONFIG} "
                  f"(pass --stub-crypto for the local Flask stub instead)")
            get_actor("router_1")["config_path"] = ROUTER_1_REAL_CRYPTO_CONFIG
            actor_names = ["downstream_host", "router_1", "upstream_1"]
        else:
            print(f"[{_now_str()}] --stub-crypto: using the local Flask crypto_host stub")
            actor_names = ["crypto_host", "downstream_host", "router_1", "upstream_1"]
        for name in actor_names:
            start_actor(name)
        narrated_sleep(2, "letting the topology settle before sustained traffic")

        before_advice = count_advice_log_lines()
        before_final = run_stress_window("before_kill", before_kill_s, warmup_s=10)
        record_stage("before_kill", before_kill_s, before_final)

        print("\n=== hard-killing crypto_host ===")
        if REAL_CRYPTO:
            docker_kill_crypto_host()
        else:
            hard_kill_actor("crypto_host")

        during_final = run_stress_window("during_kill", during_kill_s)
        record_stage("during_kill", during_kill_s, during_final)
        during_advice = count_advice_log_lines()

        print("\n=== restarting crypto_host ===")
        if REAL_CRYPTO:
            docker_start_crypto_host()
        else:
            start_actor("crypto_host")
        reset_crypto_breaker()

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

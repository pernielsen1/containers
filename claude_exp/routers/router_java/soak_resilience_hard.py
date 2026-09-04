#!/usr/bin/env python3
"""router_java port of router_py/soak_resilience_hard.py - see that file's own docstring for the
full scenario rationale (briefs/resilience_v2.md): sustained TPS traffic against router_java's real
stack, hard-killing crypto_host after a before_kill stage of healthy traffic, holding it dead for
--crypto_fail_minutes, then restarting it - all while traffic keeps flowing throughout.

Architectural difference from router_py that this script has to account for: router_java's own
router process is NOT a bare host subprocess monitor.main launches on demand - it's baked into
router_java's docker-compose `command:` (java ... RouterMain --config /config/${ROUTER_CONFIG:-
router_1.json} &, alongside the container's own local crypto_host stub), started once when the
container comes up via ./start.sh. Getting router_1 pointed at the real, shared crypto_host
container (instead of the container's own local stub) means the container itself has to be
(re)started with ROUTER_CONFIG=router_1_perf.json in the environment - see
ensure_router_container_up() - not a config_path swap on an actor dict the way router_py's script
does it. Once that's done, router_1 is already running by the time this script's actor-readiness
loop reaches it, so start_actor("router_1") below is a no-op launch (is_running() already true) +
a wait_for_ready confirmation, exactly like every other actor - no special-casing needed there.

Usage: python3 soak_resilience_hard.py [minutes] [crypto_fail_minutes] [--stub-crypto] [--comment TEXT]
  (see router_py/soak_resilience_hard.py's docstring for the meaning of each - unchanged here)
Output: console narration plus THREE rows in routers/csv_results/soak_results.csv +
soak_summary.csv (via router_py/soak_result_csv.py - the one shared CSV writer, not a second
copy), implementation="router_java_real_crypto_before_kill" / "..._during_kill" / "..._after_kill"
by default, or "router_java_before_kill" / etc. with --stub-crypto.
"""
import os
import subprocess
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
ROUTERS_ROOT = os.path.dirname(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)
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
)
from monitor.main import wait_for_ready  # noqa: E402

# soak_resilience_hard.py's per-stage 0120/0420 sent/acked counts and the final achieved_tps/error
# gate both need upstream_1's /stress_stats (a distinct route from /stats) - router_java's own
# test_resilience.py has never needed this (its scenarios use stats()/totals() instead), so it's
# defined here rather than imported, same shape as router_py's test_resilience.py's copy.
import requests  # noqa: E402


def stress_stats(name):
    actor = get_actor(name)
    try:
        r = requests.get(f"http://127.0.0.1:{actor['command_port']}/stress_stats", timeout=2)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None


# router_py/soak_result_csv.py is the one shared CSV writer for all soak scripts (router_py's own
# soak_resilience_hard.py/soak_resilience_light.py, and now this one) - see that session's
# consolidation of what used to be a hand-synced-per-language duplicate. Imported via an explicit
# sys.path entry rather than copied, so a future schema change (e.g. the `comment` column) never
# needs a third hand-sync.
sys.path.insert(0, os.path.join(ROUTERS_ROOT, "router_py"))
from soak_result_csv import record_result  # noqa: E402

TPS_TARGET = 100
POLL_INTERVAL_S = 10
GRACE_S = 5
BEFORE_KILL_FRACTION = 0.15
BEFORE_KILL_MIN_S = 15
DURING_KILL_FRACTION = 0.35
DURING_KILL_MIN_S = 15
AFTER_KILL_MIN_S = 20
BEFORE_KILL_WARMUP_S = 30

REAL_CRYPTO_STATS_URL = "http://127.0.0.1:8099/stats"
REAL_CRYPTO_CONTAINER = "crypto_host"

REAL_CRYPTO = True  # default on - see --stub-crypto in main(); read by record_stage() for the CSV label
IMPL_LABEL = "router_java_real_crypto"
COMMENT = ""  # optional --comment "text", written verbatim to soak_results.csv/soak_summary.csv

launched = []  # actors this script itself started - only these get torn down at the end


def ensure_real_crypto_up():
    """Same shared-container auto-start as router_py's soak_resilience_hard.py - if the real
    crypto_host container isn't already up, start it ourselves instead of erroring out."""
    try:
        if requests.get(REAL_CRYPTO_STATS_URL, timeout=2).status_code == 200:
            return
    except requests.RequestException:
        pass
    print(
        "shared crypto_host (port 8099) is not responding - starting it "
        "(idempotent no-op if already up)...",
        file=sys.stderr,
    )
    start_sh = os.path.join(ROUTERS_ROOT, "crypto_host", "start.sh")
    subprocess.run([start_sh], check=True)
    if requests.get(REAL_CRYPTO_STATS_URL, timeout=2).status_code != 200:
        print(f"ERROR: {start_sh} ran but crypto_host still isn't responding", file=sys.stderr)
        sys.exit(1)


def ensure_router_container_up(router_config):
    """router_java's own router process is baked into the container's compose command
    (${ROUTER_CONFIG:-router_1.json}, see docker-compose.yml), not launched via monitor.main's
    docker-exec path - so pointing it at a given config means the container has to be (re)started
    with ROUTER_CONFIG set in the environment, exactly like stress_run.sh's own perf runs
    (`ROUTER_CONFIG=router_1_perf.json ./start.sh`). `docker compose up -d --build` is a no-op if
    the rendered command hasn't changed since the container's current run, and recreates it if it
    has - safe to call unconditionally every time, same as stress_run.sh does with no separate
    "is it already right" check of its own."""
    env = os.environ.copy()
    env["ROUTER_CONFIG"] = router_config
    start_sh = os.path.join(PROJECT_ROOT, "start.sh")
    print(f"[{_now_str()}] ensuring router_java container is up with ROUTER_CONFIG={router_config} "
          f"(docker compose up -d --build; a no-op if already running with this config)...")
    subprocess.run([start_sh], check=True, cwd=PROJECT_ROOT, env=env)


def docker_kill_crypto_host():
    """SIGKILL via docker, not docker stop - a real crash / abruptly severed connection, not a
    clean shutdown, same rationale as router_py's soak."""
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
    """--stub-crypto only: router_java's own local crypto_host stub runs docker-exec'd inside the
    always-up router_java container, with no Popen handle this process can .kill() directly (see
    monitor/main.py's is_running() docstring on why - docker exec -d detaches instantly). Reuses
    monitor.main's own actor_kill_command() (already builds the exact ps/awk/kill-9 bash sequence
    for an operator to run by hand) by executing it programmatically instead - a real SIGKILL
    inside the container, same "abruptly severed, not a clean shutdown" effect as router_py's
    Popen.kill() on a host subprocess."""
    actor = get_actor(name)
    kill_script = monitor.actor_kill_command(actor)
    subprocess.run(["bash", "-c", kill_script], check=False)
    if actor in launched:
        launched.remove(actor)


def reset_crypto_breaker():
    """Mirrors router_py's soak - tells router_1 crypto_host is back *now* via the
    /crypto/reset_breaker route this session added to RouterMain.java, instead of waiting for
    CryptoClient's own self-renewing cooldown clock. Best-effort: a request hiccup here just means
    the breaker falls back to its own clock."""
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
    """Purely informational (see router_py's soak - this counter is known to be an undercount/
    best-effort, not a pass/fail signal)."""
    r = stats("router_1")
    if r is None:
        return None
    try:
        resp = requests.get("http://127.0.0.1:8080/logs", params={"format": "text"}, timeout=3)
        resp.raise_for_status()
        return sum(1 for line in resp.text.splitlines() if "0120" in line or "0420" in line)
    except requests.RequestException:
        return None


def run_stress_window(label, duration_s, tps=TPS_TARGET, warmup_s=0):
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
    record_result(row, comment=COMMENT)


def main():
    global REAL_CRYPTO, IMPL_LABEL, COMMENT
    args = sys.argv[1:]
    if "--stub-crypto" in args:
        args = [a for a in args if a != "--stub-crypto"]
        REAL_CRYPTO = False
        IMPL_LABEL = "router_java"

    if "--comment" in args:
        i = args.index("--comment")
        if i + 1 >= len(args):
            print("ERROR: --comment requires a value", file=sys.stderr)
            sys.exit(1)
        COMMENT = args[i + 1]
        args = args[:i] + args[i + 2:]

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

    print(f"[{_now_str()}] soak_resilience_hard.py (router_java) starting - {minutes:.1f} min "
          f"total: {before_kill_s}s before_kill, {during_kill_s}s during_kill "
          f"(crypto_fail_minutes={crypto_fail_minutes:.2f}"
          f"{'' if explicit_crypto_fail else ', auto'}), {after_kill_s}s after_kill.")
    print("  Every wait below is announced first with an expected min/max duration, and confirmed")
    print("  done afterward - nothing here is a silent gap.")

    try:
        if REAL_CRYPTO:
            ensure_real_crypto_up()
            ensure_router_container_up("router_1_perf.json")
            print(f"[{_now_str()}] using the real, shared crypto_host container (port 5099/8099) "
                  f"- router_1 pointed at it via config/router_1_perf.json "
                  f"(pass --stub-crypto for the container's own local stub instead)")
            actor_names = ["downstream_host", "router_1", "upstream_1"]
        else:
            ensure_router_container_up("router_1.json")
            print(f"[{_now_str()}] --stub-crypto: using router_java's own container-local crypto_host stub")
            actor_names = ["crypto_host", "downstream_host", "router_1", "upstream_1"]
        for name in actor_names:
            start_actor(name)
        narrated_sleep(2, "letting the topology settle before sustained traffic")

        before_advice = count_advice_log_lines()
        before_final = run_stress_window("before_kill", before_kill_s, warmup_s=BEFORE_KILL_WARMUP_S)
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

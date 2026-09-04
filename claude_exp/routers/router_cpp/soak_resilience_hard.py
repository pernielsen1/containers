#!/usr/bin/env python3
"""C++ port of router_py/soak_resilience_hard.py - same before_kill/during_kill/after_kill
structure (sustained TPS traffic, hard-kill the real shared crypto_host container mid-run, hold it
dead for a while, restart it, keep measuring) against router_cpp instead. See router_py's version
for the full rationale (briefs/resilience_v2.md); this docstring only covers what differs here.

**Why this isn't a line-for-line translation.** router_py's router_1 is a bare host subprocess
that monitor.main.launch_actor() starts directly with a swappable --config path - real-crypto mode
there is just "point the config_path field at a different file before calling start_actor()".
router_cpp's router_1 instead runs *inside an always-up docker container*
(monitor/main.py's CONTAINER_NAME), started via docker-compose, whose command line bakes in
`--config /config/${ROUTER_CONFIG:-router_1.json}` at container-start time (see
docker-compose.yml's own comment) - so selecting real-crypto mode here means exporting
ROUTER_CONFIG=router_1_perf.json before calling ./start.sh (same recipe stress_run.sh's perf runs
already use, reused verbatim rather than reinvented), not a post-hoc field swap. downstream_host/
upstream_host are the same shared Python simulators router_py uses, but - because
monitor.main.launch_actor()'s generic config-fallback (actor.get("downstream_config_path") or
actor.get("upstream_config_path")) doesn't know about the *_perf.json variants stress_run.sh needs
- they're launched directly here as host subprocesses with an explicit --config, exactly like
stress_run.sh itself does, rather than through launch_actor().

Usage: python3 soak_resilience_hard.py [minutes] [crypto_fail_minutes] [--comment "text"]
  Same meaning as router_py's version. No --stub-crypto here (router_cpp has no equivalent local
  stub scenario built into this script - only the real, shared crypto_host container is
  supported). See router_py/soak_resilience_hard.py's docstring for the minutes/crypto_fail_minutes
  semantics and the reasoning behind the stage-length fractions/floors below (copied unchanged).
Output: same csv_results/soak_results.csv + soak_summary.csv (via router_py/soak_result_csv.py's
record_result() - reused directly rather than duplicated a third time), implementation label
"router_cpp_real_crypto_before_kill" / "..._during_kill" / "..._after_kill".
Prerequisite: none - ensure_real_crypto_up() and ensure_router_container_up() both self-start
what they need, idempotently, same as router_py's version.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import monitor.main as monitor  # noqa: E402
from test_resilience import (  # noqa: E402
    CSV_FILE,
    ROUTER_NAME,
    _now_str,
    announce,
    done_waiting,
    get_actor,
    narrated_sleep,
    send_test_csv,
    stats,
    wait_for_ready,
)

import requests  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
ROUTERS_ROOT = os.path.dirname(PROJECT_ROOT)
sys.path.insert(0, os.path.join(ROUTERS_ROOT, "router_py"))
from soak_result_csv import record_result  # noqa: E402

# Same target/timing constants as router_py's version - see that file's own comments for the
# reasoning (TPS_TARGET's ~140 req/s-stub-ceiling history doesn't apply here since this script
# only ever targets the real crypto_host container, but the number itself is unchanged so the two
# languages' soak numbers are directly comparable).
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

DOWNSTREAM_PERF_CONFIG = os.path.join(PROJECT_ROOT, "config", "downstream_host_perf.json")
UPSTREAM_PERF_CONFIG = os.path.join(ROUTERS_ROOT, "upstream_host", "config_perf.json")
DOWNSTREAM_CMD_PORT = 8081
UPSTREAM_CMD_PORT = 8083

IMPL_LABEL = "router_cpp_real_crypto"
COMMENT = ""  # optional --comment "text", written verbatim to soak_results.csv/soak_summary.csv

_host_procs = {}  # name -> Popen, for downstream_host/upstream_host - launched directly below,
                   # not via monitor.launch_actor() (see module docstring)


def ensure_real_crypto_up():
    """Identical to router_py's version - same shared container, same idempotent self-start."""
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


def docker_kill_crypto_host():
    """SIGKILL via docker against the shared crypto_host container - identical to router_py's
    version, same container, same rationale (real crash, not a clean shutdown)."""
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


def ensure_router_container_up():
    """Brings up (or, if it's already running under a different ROUTER_CONFIG, recreates) the
    router_cpp docker-compose stack pointed at the real shared crypto_host container - same
    ROUTER_CONFIG=router_1_perf.json recipe stress_run.sh's perf runs already use. ROUTER_CONFIG is
    read by docker-compose.yml's command at container-start time (interpolated by compose itself),
    so this must be exported before ./start.sh runs, not applied after the fact - `docker compose
    up -d` is idempotent but will recreate the container if the rendered command differs from what
    the running container was started with, which is exactly how switching configs here works."""
    env = {**os.environ, "ROUTER_CONFIG": "router_1_perf.json"}
    print(f"[{_now_str()}] bringing up router_cpp (ROUTER_CONFIG=router_1_perf.json)...")
    subprocess.run(["./start.sh"], cwd=PROJECT_ROOT, env=env, check=True, stdout=sys.stderr)


def start_host_actor(name, cmd, cwd, ready_port, timeout=15):
    """Launches downstream_host/upstream_host directly as host subprocesses with an explicit perf
    config - see module docstring for why this bypasses monitor.launch_actor()'s generic (non-perf)
    config fallback. Idempotent: a still-running previous instance from an earlier call in the same
    process is left alone rather than relaunched."""
    proc = _host_procs.get(name)
    if proc is None or proc.poll() is not None:
        proc = subprocess.Popen(cmd, cwd=cwd)
        _host_procs[name] = proc
    announce(f"waiting for {name} to become ready", 0, timeout)
    start = time.time()
    deadline = start + timeout
    while time.time() < deadline:
        try:
            if requests.get(f"http://127.0.0.1:{ready_port}/stats", timeout=1).status_code == 200:
                done_waiting(f"{name} ready", time.time() - start)
                return
        except requests.RequestException:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"{name} did not become ready within {timeout}s")


def reset_crypto_breaker():
    """Tells router_1 crypto_host is back *now* instead of letting its breaker discover that on
    its own self-renewing cooldown clock - identical rationale to router_py's version. Called
    right after docker_start_crypto_host() confirms the real service port is open."""
    actor = get_actor(ROUTER_NAME)
    port = actor["command_port"]
    try:
        requests.post(
            f"http://127.0.0.1:{port}/crypto/reset_breaker",
            headers=monitor.auth_headers(actor), timeout=3,
        )
    except requests.RequestException as e:
        print(f"  (crypto breaker reset failed, falling back to its own cooldown clock: {e})")


def stress_stats(name):
    """router_cpp's own test_resilience.py has no stress_stats() (its scenarios don't need
    per-window sent/received/latency percentiles) - upstream_host's /stress_stats route is shared
    across all three languages regardless, so this is the same 8-line helper router_py's
    test_resilience.py already has, just not otherwise available here."""
    actor = get_actor(name)
    try:
        r = requests.get(f"http://127.0.0.1:{actor['command_port']}/stress_stats", timeout=2)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None


def teardown():
    """Mirrors stress_run.sh's own cleanup() - graceful /stop to the two host-launched simulators
    first, then tear the whole router_cpp container down via ./stop.sh (compose down). Does not
    touch the shared crypto_host container - that outlives this script, same as router_py's
    version never tears down the shared container either."""
    for name, port in (("upstream_host", UPSTREAM_CMD_PORT), ("downstream_host", DOWNSTREAM_CMD_PORT)):
        proc = _host_procs.pop(name, None)
        if proc is None:
            continue
        try:
            requests.post(f"http://127.0.0.1:{port}/stop", timeout=3)
        except requests.RequestException:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        print(f"[teardown] stopped {name}")
    try:
        subprocess.run(["./stop.sh"], cwd=PROJECT_ROOT, check=True, capture_output=True)
        print("[teardown] stopped router_cpp container")
    except subprocess.CalledProcessError as e:
        print(f"[teardown] ./stop.sh failed: {e}")


def count_advice_log_lines():
    """Identical purpose to router_py's version - see that file's docstring. router_cpp's /logs
    route is assumed to accept the same format=text query param (shared CommandServer contract);
    unverified here specifically - see this script's own TODO note in the port report."""
    r = stats(ROUTER_NAME)
    if r is None:
        return None
    try:
        resp = requests.get("http://127.0.0.1:8080/logs", params={"format": "text"}, timeout=3)
        resp.raise_for_status()
        return sum(1 for line in resp.text.splitlines() if "0120" in line or "0420" in line)
    except requests.RequestException:
        return None


def run_stress_window(label, duration_s, tps=TPS_TARGET, warmup_s=0):
    """Identical to router_py's version - upstream_host is the same shared component either way."""
    print(f"\n=== STAGE: {label} ({duration_s}s @ {tps} TPS) ===")
    actor = get_actor("upstream_host")
    port = actor["command_port"]
    with open(CSV_FILE, "rb") as f:
        requests.post(f"http://127.0.0.1:{port}/upload", files={"file": f}, timeout=5)
    r = requests.get(
        f"http://127.0.0.1:{port}/start",
        params={"rate": tps, "duration": duration_s, "warmup_s": warmup_s},
        timeout=5,
    )
    print(f"upstream_host: stress start status={r.status_code} body={r.text}")

    deadline = time.time() + warmup_s + 2 + duration_s
    while time.time() < deadline:
        time.sleep(min(POLL_INTERVAL_S, max(0.0, deadline - time.time())))
        r_stats = stats(ROUTER_NAME) or {}
        u_stats = stress_stats("upstream_host") or {}
        conns = r_stats.get("connections", {})
        gauges = r_stats.get("gauges", {})
        latency = r_stats.get("latency", {})

        def hop(name):
            b = latency.get(name)
            return f"{name}=p50:{b['p50_ms']}/max:{b['max_ms']}" if b else f"{name}=n/a"

        print(
            f"[{_now_str()}] router_1: connections={conns} queue_depth={gauges.get('queue_depth')} "
            f"response_queue_depth={gauges.get('response_queue_depth')} "
            f"pending_count={gauges.get('pending_count')} | hops(ms): {hop('queue_wait')} "
            f"{hop('crypto_rtt')} {hop('downstream_rtt')} {hop('total')} | upstream_host: "
            f"achieved_tps={u_stats.get('achieved_tps')} sent={u_stats.get('sent')} "
            f"received={u_stats.get('received')} errors={u_stats.get('errors')} | advice: "
            f"0120 sent={u_stats.get('advice_0120_sent')}/acked={u_stats.get('advice_0120_acked')} "
            f"0420 sent={u_stats.get('advice_0420_sent')}/acked={u_stats.get('advice_0420_acked')}"
        )

    narrated_sleep(GRACE_S, f"{label}: letting the window's tail settle before reading final stats")
    final = stress_stats("upstream_host") or {}
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
    global COMMENT
    args = sys.argv[1:]

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

    print(f"[{_now_str()}] soak_resilience_hard.py (router_cpp) starting - {minutes:.1f} min "
          f"total: {before_kill_s}s before_kill, {during_kill_s}s during_kill "
          f"(crypto_fail_minutes={crypto_fail_minutes:.2f}"
          f"{'' if explicit_crypto_fail else ', auto'}), {after_kill_s}s after_kill.")
    print("  Every wait below is announced first with an expected min/max duration, and confirmed")
    print("  done afterward - nothing here is a silent gap.")

    overall_ok = False
    try:
        ensure_real_crypto_up()
        print(f"[{_now_str()}] using the real, shared crypto_host container (port 5099/8099) "
              f"- router_cpp pointed at it via ROUTER_CONFIG=router_1_perf.json")

        start_host_actor(
            "downstream_host",
            [sys.executable, os.path.join(ROUTERS_ROOT, "downstream_host", "main.py"),
             "--config", DOWNSTREAM_PERF_CONFIG],
            cwd=PROJECT_ROOT, ready_port=DOWNSTREAM_CMD_PORT,
        )
        ensure_router_container_up()
        wait_for_ready(get_actor(ROUTER_NAME), timeout=15)
        start_host_actor(
            "upstream_host",
            [sys.executable, os.path.join(ROUTERS_ROOT, "upstream_host", "main.py"),
             "--config", UPSTREAM_PERF_CONFIG, "--router-host", "127.0.0.1"],
            cwd=PROJECT_ROOT, ready_port=UPSTREAM_CMD_PORT,
        )
        narrated_sleep(2, "letting the topology settle before sustained traffic")

        before_advice = count_advice_log_lines()
        before_final = run_stress_window("before_kill", before_kill_s, warmup_s=BEFORE_KILL_WARMUP_S)
        record_stage("before_kill", before_kill_s, before_final)

        print("\n=== hard-killing crypto_host ===")
        docker_kill_crypto_host()

        during_final = run_stress_window("during_kill", during_kill_s)
        record_stage("during_kill", during_kill_s, during_final)
        during_advice = count_advice_log_lines()

        print("\n=== restarting crypto_host ===")
        docker_start_crypto_host()
        reset_crypto_breaker()

        after_final = run_stress_window("after_kill", after_kill_s)
        record_stage("after_kill", after_kill_s, after_final)
        after_advice = count_advice_log_lines()

        results = send_test_csv("upstream_host")
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
        print(f"\n[{_now_str()}] soak_resilience_hard.py (router_cpp) finished: "
              f"{'PASS' if overall_ok else 'FAIL'}")
    finally:
        teardown()

    if not overall_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()

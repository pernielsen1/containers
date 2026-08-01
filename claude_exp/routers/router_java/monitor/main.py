import argparse
import json
import logging
import os
import subprocess
import sys
import threading
import time

import requests
from flask import Flask, jsonify, request, send_from_directory

# This monitor deliberately runs on the HOST, not inside the router_java container: it's a thin,
# language-agnostic dashboard that talks to each actor's CommandServer over plain HTTP (the same
# /stats, /stop, /log_level, /logs contract as router_py's Python CommandServer) - it doesn't care that
# the actors behind it are JVMs instead of Python processes. Ported from router_py/monitor/main.py;
# the only real adaptations are how actors are launched/tracked (docker exec into the running
# container instead of a host subprocess) and how "is it running" is determined (HTTP liveness
# instead of a Popen handle, since `docker exec -d` detaches immediately - see is_running()).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTAINER_NAME = "router_java"

# upstream_host is shared across all three implementations (routers/upstream_host/), not a Java
# actor anymore - see routers/upstream_host/build_router.md. Launched as a host subprocess
# (like router_py's monitor always did), not via docker exec into CONTAINER_NAME.
UPSTREAM_HOST_DIR = os.path.join(os.path.dirname(PROJECT_ROOT), "upstream_host")

MAIN_CLASS_BY_TYPE = {
    "router": "com.xv6.router.RouterMain",
    "downstream": "com.xv6.simulators.downstreamhost.DownstreamHostMain",
    "crypto": "com.xv6.simulators.cryptohost.CryptoHostMain",
}
STARTUP_ORDER = {"crypto": 0, "downstream": 1, "router": 2, "upstream": 3}

logger = logging.getLogger(__name__)

_actors_cache = None
_actors_lock = threading.Lock()

_starting = False
_starting_lock = threading.Lock()

# Only the shared upstream_host actor is tracked here (a real host Popen handle) - every other
# actor type is launched via `docker exec -d` (see launch_actor()), which detaches instantly and
# has no Popen handle to track in the first place.
_processes = {}
_processes_lock = threading.Lock()


def discover_actors():
    global _actors_cache
    with _actors_lock:
        if _actors_cache is not None:
            return _actors_cache

        found = []
        for root, dirs, files in os.walk(PROJECT_ROOT):
            dirs[:] = [d for d in dirs if d != "monitor" and d != "target" and not d.startswith(".")]
            if "config.json" in files:
                path = os.path.join(root, "config.json")
            else:
                path = None
            # router_java keeps all actor configs as config/<name>.json rather than one config.json
            # per actor directory (router_py's layout) - check every *.json under config/ too.
            for fn in files:
                if root.endswith(os.sep + "config") and fn.endswith(".json"):
                    _consider(found, os.path.join(root, fn))
            if path:
                _consider(found, path)

        # The walk above only ever covers PROJECT_ROOT (router_java/), so it can never find
        # upstream_host's config - it lives in the shared routers/upstream_host/ directory,
        # outside this tree entirely. Add it explicitly.
        upstream_config_path = os.path.join(UPSTREAM_HOST_DIR, "config.json")
        try:
            with open(upstream_config_path) as f:
                upstream_cfg = json.load(f)
            found.append(
                {
                    "name": upstream_cfg.get("name"),
                    "type": upstream_cfg.get("type"),
                    "command_port": upstream_cfg.get("command_port"),
                    "config_path": upstream_config_path,
                    "is_active": upstream_cfg.get("is_active", True),
                }
            )
        except (OSError, json.JSONDecodeError):
            pass

        found.sort(key=lambda a: STARTUP_ORDER.get(a["type"], 99))
        _actors_cache = found
        return _actors_cache


def _consider(found, path):
    try:
        with open(path) as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        return
    name = cfg.get("name")
    actor_type = cfg.get("type")
    # "upstream" has no MAIN_CLASS_BY_TYPE entry (launch_actor() special-cases it as a host
    # subprocess of the shared upstream_host binary instead of a docker-exec'd Java main class),
    # but it's still a valid discoverable actor type - e.g. a per-implementation-local
    # config/upstream_2.json, mirroring router_py's simulators/upstream_2/config.json pattern.
    if not name or (actor_type not in MAIN_CLASS_BY_TYPE and actor_type != "upstream"):
        return
    if any(a["name"] == name for a in found):
        return
    found.append(
        {
            "name": name,
            "type": actor_type,
            "command_port": cfg.get("command_port"),
            "config_path": path,
            "is_active": cfg.get("is_active", True),
        }
    )


def get_actors():
    return discover_actors()


def get_actor(name):
    return next((a for a in get_actors() if a["name"] == name), None)


def is_running(name):
    """No Popen handle exists to poll: actors are launched via `docker exec -d`, whose client
    process exits the instant the detached command starts inside the container. Liveness is
    therefore defined as "the actor's own /stats endpoint answers" rather than "the process we
    spawned hasn't exited" - arguably more honest for a dev tool anyway."""
    actor = get_actor(name)
    if actor is None:
        return False
    try:
        resp = requests.get(f"http://127.0.0.1:{actor['command_port']}/stats", timeout=1)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def launch_actor(actor):
    if actor["type"] == "upstream":
        proc = subprocess.Popen(
            [sys.executable, os.path.join(UPSTREAM_HOST_DIR, "main.py"), "--config", actor["config_path"]],
            cwd=UPSTREAM_HOST_DIR,
        )
        with _processes_lock:
            _processes[actor["name"]] = proc
        logger.info("launched %s as a host subprocess (pid=%s)", actor["name"], proc.pid)
        return

    main_class = MAIN_CLASS_BY_TYPE[actor["type"]]
    rel_config = os.path.relpath(actor["config_path"], PROJECT_ROOT)
    # stdout/stderr redirected to a file inside the container (truncated each launch, so
    # `tail -F` always reflects the current run) so an operator can `docker exec ... tail -F` it
    # by hand - see /api/actor/<name>/commands. `docker exec -d`'s own stdout/stderr would
    # otherwise just be discarded, since the client detaches immediately.
    java_cmd = (
        f"mkdir -p logs && java -cp target/router_java.jar {main_class} "
        f"--config {rel_config} > logs/{actor['name']}.console.log 2>&1"
    )
    cmd = ["docker", "exec", "-d", CONTAINER_NAME, "bash", "-c", java_cmd]
    subprocess.run(cmd, check=True, cwd=PROJECT_ROOT)
    logger.info("launched %s via docker exec (%s)", actor["name"], main_class)


def actor_console_log_path(actor):
    return f"logs/{actor['name']}.console.log"


def actor_kill_command(actor):
    if actor["type"] == "upstream":
        with _processes_lock:
            proc = _processes.get(actor["name"])
        pid = proc.pid if proc is not None else None
        if pid is None:
            return f'pkill -f "{os.path.join(UPSTREAM_HOST_DIR, "main.py")}"'
        return f"kill -9 {pid}"

    main_class = MAIN_CLASS_BY_TYPE[actor["type"]]
    rel_config = os.path.relpath(actor["config_path"], PROJECT_ROOT)
    # jps -lm prints "<pid> <main class> <program args>" - matching on class+config together
    # (not just class) disambiguates actors that share a main class but differ by config, e.g.
    # multiple router instances (see /api/routers_by_partner). Presented as a small multi-line
    # script rather than a single `bash -c '...'` one-liner: it's meant to be read and pasted by
    # an operator, and running jps/grep/cut on the operator's own host shell (only `jps` and the
    # final `kill` actually need `docker exec`) avoids the nested-quoting a one-liner would need
    # to protect $PID/$(...) from the operator's shell while still letting it reach the inner one.
    pattern = f"{main_class} --config {rel_config}"
    return "\n".join([
        "#!/usr/bin/env bash",
        f'PATTERN="{pattern}"',
        f'PID=$(docker exec {CONTAINER_NAME} jps -lm | grep -F "$PATTERN" | cut -d" " -f1)',
        'if [ -z "$PID" ]; then',
        '  echo "No matching process found for: $PATTERN" >&2',
        "  exit 1",
        "fi",
        'echo "Killing PID $PID ($PATTERN)"',
        f'docker exec {CONTAINER_NAME} kill -9 "$PID"',
    ])


def actor_tail_command(actor):
    if actor["type"] == "upstream":
        return "(no log file - upstream_host runs as a host subprocess with inherited stdout/stderr)"
    return f"docker exec {CONTAINER_NAME} tail -F {actor_console_log_path(actor)}"


def stop_actor(actor):
    try:
        requests.post(f"http://127.0.0.1:{actor['command_port']}/stop", timeout=3)
    except requests.RequestException:
        pass
    # No process handle to wait() on for docker-exec'd actors; poll HTTP liveness instead so
    # callers (stop_all, the /stop route) don't report success before the JVM has actually
    # exited. upstream_host is the one actor type with a real Popen handle (see launch_actor()) -
    # fall back to killing it directly if /stop somehow didn't land.
    deadline = time.time() + 5
    while time.time() < deadline and is_running(actor["name"]):
        time.sleep(0.2)
    with _processes_lock:
        proc = _processes.get(actor["name"])
    if proc is not None:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        with _processes_lock:
            if _processes.get(actor["name"]) is proc:
                del _processes[actor["name"]]


def wait_for_ready(actor, timeout=10):
    """Polls /stats until the actor answers 200, and - for router/upstream - until its
    downstream/router connection is up. Without the connection check, a /start called
    immediately after "Start All" can 503 with "not connected to router" even though every
    /stats already answers 200."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(f"http://127.0.0.1:{actor['command_port']}/stats", timeout=1)
            if resp.status_code == 200:
                connections = resp.json().get("connections", {})
                if actor["type"] == "router":
                    if connections.get("downstream"):
                        return
                elif actor["type"] == "upstream":
                    if connections.get("router"):
                        return
                else:
                    return
        except Exception:
            pass
        time.sleep(0.3)
    logger.warning("wait_for_ready timed out for %s", actor["name"])


def _start_all_worker():
    global _starting
    try:
        for actor in get_actors():
            if not actor["is_active"]:
                continue
            if not is_running(actor["name"]):
                launch_actor(actor)
            wait_for_ready(actor, timeout=10)
    finally:
        with _starting_lock:
            _starting = False


def _terminate_all():
    """Best-effort: POST /stop to every actor that's currently up. Unlike router_py (where the
    monitor held a real Popen per actor and could terminate()/kill() it directly), there is no
    process handle here to fall back on if an actor ignores /stop - the container itself
    (`./stop.sh`) is the hard backstop, same as it is for run_test.sh."""
    for actor in get_actors():
        if is_running(actor["name"]):
            try:
                requests.post(f"http://127.0.0.1:{actor['command_port']}/stop", timeout=2)
            except requests.RequestException:
                pass


def _make_app(_port):
    app = Flask(__name__, static_folder=None)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

    @app.route("/")
    def index():
        return send_from_directory(static_dir, "index.html")

    @app.route("/api/actors")
    def actors():
        result = [
            {
                "name": a["name"],
                "type": a["type"],
                "command_port": a["command_port"],
                "running": is_running(a["name"]),
                "is_active": a["is_active"],
            }
            for a in get_actors()
        ]
        return jsonify(result)

    @app.route("/api/routers_by_partner")
    def routers_by_partner():
        result = {}
        for a in get_actors():
            if a["type"] != "router":
                continue
            try:
                with open(a["config_path"]) as f:
                    cfg = json.load(f)
            except OSError:
                continue
            partner_id = cfg.get("partner_id", "unknown")
            result.setdefault(partner_id, []).append({"name": a["name"], "command_port": a["command_port"]})
        return jsonify(result)

    def _actor_status(actor):
        try:
            resp = requests.get(f"http://127.0.0.1:{actor['command_port']}/stats", timeout=2)
            if resp.status_code != 200:
                return "red"
            data = resp.json()
        except Exception:
            return "red"

        threshold = data.get("yellow_threshold_seconds")
        if threshold is None:
            return "green"
        seconds_since = data.get("seconds_since_last_recv")
        if seconds_since is None or seconds_since > threshold:
            return "yellow"
        return "green"

    @app.route("/api/status")
    def status():
        result = {}
        lock = threading.Lock()

        def worker(actor):
            s = _actor_status(actor)
            with lock:
                result[actor["name"]] = s

        threads = [threading.Thread(target=worker, args=(a,)) for a in get_actors()]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        return jsonify(result)

    @app.route("/api/commands")
    def commands():
        return jsonify({"shell": f"docker exec -it {CONTAINER_NAME} bash"})

    @app.route("/api/actor/<name>/commands")
    def actor_commands(name):
        actor = get_actor(name)
        if not actor:
            return jsonify({"error": "not found"}), 404
        return jsonify({
            "kill": actor_kill_command(actor),
            "tail": actor_tail_command(actor),
        })

    @app.route("/api/starting")
    def starting():
        with _starting_lock:
            return jsonify({"starting": _starting})

    @app.route("/api/csv_files")
    def csv_files():
        files = []
        test_dir = os.path.join(PROJECT_ROOT, "test_csv_files")
        if os.path.isdir(test_dir):
            for fn in sorted(os.listdir(test_dir)):
                if fn.endswith(".csv"):
                    files.append(os.path.relpath(os.path.join(test_dir, fn), PROJECT_ROOT))
        for a in get_actors():
            if a["type"] != "upstream":
                continue
            try:
                with open(a["config_path"]) as f:
                    acfg = json.load(f)
            except OSError:
                continue
            # router_java's upstream configs name their own input dir (e.g. "upstream_1_input")
            # rather than router_py's fixed "input" subfolder - read it instead of assuming.
            input_dir_name = acfg.get("input_dir", "input")
            input_dir = os.path.join(os.path.dirname(a["config_path"]), input_dir_name)
            if os.path.isdir(input_dir):
                for fn in sorted(os.listdir(input_dir)):
                    if fn.endswith(".csv"):
                        files.append(os.path.relpath(os.path.join(input_dir, fn), PROJECT_ROOT))
        return jsonify(files)

    @app.route("/api/actor/<name>/launch", methods=["POST"])
    def actor_launch(name):
        actor = get_actor(name)
        if not actor:
            return jsonify({"error": "not found"}), 404
        if not is_running(name):
            launch_actor(actor)
        return jsonify({"status": "launched"})

    @app.route("/api/actor/<name>/stop", methods=["POST"])
    def actor_stop(name):
        actor = get_actor(name)
        if not actor:
            return jsonify({"error": "not found"}), 404
        stop_actor(actor)
        return jsonify({"status": "stopped"})

    def _proxy_get(name, path):
        actor = get_actor(name)
        if not actor:
            return jsonify({"error": "not found"}), 404
        try:
            resp = requests.get(f"http://127.0.0.1:{actor['command_port']}/{path}", timeout=5)
            return resp.text, resp.status_code, {"Content-Type": resp.headers.get("Content-Type", "application/json")}
        except requests.RequestException as e:
            return jsonify({"error": str(e)}), 502

    def _proxy_post(name, path, json_body=None):
        actor = get_actor(name)
        if not actor:
            return jsonify({"error": "not found"}), 404
        try:
            resp = requests.post(f"http://127.0.0.1:{actor['command_port']}/{path}", json=json_body, timeout=5)
            return resp.text, resp.status_code, {"Content-Type": resp.headers.get("Content-Type", "application/json")}
        except requests.RequestException as e:
            return jsonify({"error": str(e)}), 502

    @app.route("/api/actor/<name>/stats")
    def actor_stats(name):
        return _proxy_get(name, "stats")

    @app.route("/api/actor/<name>/start")
    def actor_start(name):
        return _proxy_get(name, "start")

    @app.route("/api/actor/<name>/results")
    def actor_results(name):
        return _proxy_get(name, "results")

    @app.route("/api/actor/<name>/log_level", methods=["GET", "POST"])
    def actor_log_level(name):
        if request.method == "POST":
            return _proxy_post(name, "log_level", json_body=request.json)
        return _proxy_get(name, "log_level")

    @app.route("/api/actor/<name>/logs")
    def actor_logs(name):
        fmt = request.args.get("format", "json")
        return _proxy_get(name, f"logs?format={fmt}")

    @app.route("/api/actor/<name>/upload", methods=["POST"])
    def actor_upload(name):
        actor = get_actor(name)
        if not actor:
            return jsonify({"error": "not found"}), 404
        port = actor["command_port"]
        try:
            f = request.files.get("file")
            if f is None:
                return jsonify({"error": "no file"}), 400
            resp = requests.post(
                f"http://127.0.0.1:{port}/upload",
                files={"file": (f.filename, f.read(), f.content_type)},
                timeout=10,
            )
            return resp.text, resp.status_code, {"Content-Type": "application/json"}
        except Exception as e:
            return jsonify({"error": str(e)}), 502

    @app.route("/api/actor/<name>/upload_path", methods=["POST"])
    def actor_upload_path(name):
        actor = get_actor(name)
        if not actor:
            return jsonify({"error": "not found"}), 404
        port = actor["command_port"]
        body = request.json or {}
        rel_path = body.get("path", "")
        abs_path = os.path.normpath(os.path.join(PROJECT_ROOT, rel_path))
        if not os.path.exists(abs_path):
            return jsonify({"error": "file not found"}), 404
        with open(abs_path, "rb") as f:
            content = f.read()
        try:
            resp = requests.post(
                f"http://127.0.0.1:{port}/upload",
                files={"file": (os.path.basename(abs_path), content, "text/csv")},
                timeout=10,
            )
            return resp.text, resp.status_code, {"Content-Type": "application/json"}
        except Exception as e:
            return jsonify({"error": str(e)}), 502

    @app.route("/api/actor/<name>/dispatcher/purge", methods=["POST"])
    def actor_purge(name):
        return _proxy_post(name, "dispatcher/purge")

    @app.route("/api/start_all", methods=["POST"])
    def start_all():
        global _starting
        with _starting_lock:
            if _starting:
                return jsonify({"status": "already starting"})
            _starting = True
        t = threading.Thread(target=_start_all_worker, daemon=True)
        t.start()
        return jsonify({"status": "starting"})

    @app.route("/api/stop_all", methods=["POST"])
    def stop_all():
        for a in reversed(get_actors()):
            if is_running(a["name"]):
                stop_actor(a)
        return jsonify({"status": "stopped"})

    @app.route("/stop", methods=["POST"])
    def stop_monitor():
        def _shutdown():
            time.sleep(0.2)
            _terminate_all()
            os._exit(0)

        threading.Thread(target=_shutdown, daemon=True).start()
        return jsonify({"status": "stopping"})

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    app = _make_app(args.port)
    logger.info("monitor listening on port %d (router_java, actors launched via docker exec)", args.port)
    app.run(host="0.0.0.0", port=args.port, use_reloader=False)


if __name__ == "__main__":
    main()

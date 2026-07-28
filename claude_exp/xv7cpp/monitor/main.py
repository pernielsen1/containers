#!/usr/bin/env python3
"""xv7cpp dashboard: a thin Flask app that talks to every actor's CommandServer purely over
HTTP (/stats, /stop, /log_level, /logs, plus upstream's /start//results//upload). Runs on the
host, not in the container -- the actors are only reachable at localhost because the xv7cpp
container runs with network_mode: host.

This project keeps one shared config/router_1.json read by all four binaries (rather than one
JSON file per actor), so "actor discovery" here means synthesizing four logical actor
descriptors from that single file's nested upstream/downstream/crypto blocks, not scanning a
directory of per-actor files.
"""

import json
import os
import subprocess
import threading
import time
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_from_directory

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
CONTAINER_NAME = "xv7cpp"
CONFIG_REL_PATH = "config/router_1.json"   # relative to PROJECT_ROOT, and to the container's WORKDIR
CONFIG_ABS_PATH_IN_CONTAINER = "/config/router_1.json"
BUILD_DIR_IN_CONTAINER = "/src/build"
LOGS_DIR_IN_CONTAINER = "/src/logs"

BINARY_BY_TYPE = {
    "router": "router_main",
    "upstream": "upstream_host",
    "downstream": "downstream_host",
    "crypto": "crypto_host",
}
STARTUP_ORDER = {"crypto": 0, "downstream": 1, "router": 2, "upstream": 3}

app = Flask(__name__, static_folder=None)

_actors_cache = None
_starting_lock = threading.Lock()
_starting = False


def discover_actors():
    """Synthesizes the four logical actors from the one shared config file. Cached for the
    monitor's lifetime -- restart the monitor to pick up config edits, matching the documented
    "cached once per monitor lifetime" behavior."""
    global _actors_cache
    if _actors_cache is not None:
        return _actors_cache

    with open(PROJECT_ROOT / CONFIG_REL_PATH) as f:
        cfg = json.load(f)

    actors = [
        {
            "name": cfg.get("name", "router_1"),
            "type": "router",
            "command_port": cfg.get("command_port", 8080),
            "auth_token": cfg.get("command_auth_token"),
            "partner_id": cfg.get("partner_id"),
            "is_active": True,
        },
        {
            "name": "downstream_host",
            "type": "downstream",
            "command_port": cfg.get("downstream", {}).get("command_port", 8081),
            "auth_token": None,
            "partner_id": None,
            "is_active": True,
        },
        {
            "name": "crypto_host",
            "type": "crypto",
            "command_port": cfg.get("crypto", {}).get("command_port", 8082),
            "auth_token": None,
            "partner_id": None,
            "is_active": True,
        },
        {
            "name": "upstream_host",
            "type": "upstream",
            "command_port": cfg.get("upstream", {}).get("command_port", 8083),
            "auth_token": None,
            "partner_id": None,
            "is_active": True,
        },
    ]
    for a in actors:
        a["binary"] = BINARY_BY_TYPE[a["type"]]
    _actors_cache = actors
    return actors


def get_actor(name):
    for a in discover_actors():
        if a["name"] == name:
            return a
    return None


def auth_headers(actor):
    token = actor.get("auth_token")
    return {"X-Router-Auth": token} if token else {}


def is_running(actor):
    """No process handle to poll -- docker exec -d's client exits immediately once the detached
    command starts. Liveness is "the actor's own /stats endpoint answers HTTP 200"."""
    try:
        r = requests.get(f"http://localhost:{actor['command_port']}/stats", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def wait_for_ready(actor, timeout=10):
    """Polls /stats until it answers 200, and -- for routers, until connections.downstream is
    true; for upstreams, until connections.router is true -- since the HTTP server coming up and
    the actor's own TCP-level connection to its peer coming up are two different milestones."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"http://localhost:{actor['command_port']}/stats", timeout=2)
            if r.status_code == 200:
                conns = r.json().get("connections", {})
                if actor["type"] == "router" and not conns.get("downstream"):
                    pass
                elif actor["type"] == "upstream" and not conns.get("router"):
                    pass
                else:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def launch_actor(actor):
    binary_path = f"{BUILD_DIR_IN_CONTAINER}/{actor['binary']}"
    cmd = (
        f"mkdir -p {LOGS_DIR_IN_CONTAINER} && "
        f"{binary_path} --config {CONFIG_ABS_PATH_IN_CONTAINER} "
        f"> {LOGS_DIR_IN_CONTAINER}/{actor['name']}.console.log 2>&1"
    )
    subprocess.run(["docker", "exec", "-d", CONTAINER_NAME, "bash", "-c", cmd], check=True)


def actor_commands(actor):
    """Console-visibility commands for the dashboard: no embedded terminal (the monitor binds
    0.0.0.0:8090, LAN-reachable, and an unauthenticated shell over HTTP isn't worth it for a dev
    tool) -- just copy-pasteable commands. Matches on the full binary path + config argument
    string, not just the binary name, so this stays correct if a future multi-router scenario
    means the bare binary name is no longer unique.

    Match must be anchored to the start of the command (after stripping the PID column), not a
    bare substring search -- PID 1 is docker-init/tini, and `ps` shows its own argv as the entire
    wrapped shell script text (every actor's invocation concatenated together), which trivially
    contains any single actor's pattern as a substring. A plain `grep -F` would match PID 1 first
    and kill the whole container instead of the intended single actor."""
    binary_path = f"{BUILD_DIR_IN_CONTAINER}/{actor['binary']}"
    pattern = f"{binary_path} --config {CONFIG_ABS_PATH_IN_CONTAINER}"
    kill_script = (
        f'PATTERN="{pattern}"\n'
        f'PID=$(docker exec {CONTAINER_NAME} sh -c "ps -eo pid,args" | '
        f"awk -v pat=\"$PATTERN\" '{{cmd=$0; sub(/^[ \\t]*[0-9]+[ \\t]+/, \"\", cmd); "
        f"if (index(cmd, pat) == 1) print $1}}')\n"
        f'if [ -z "$PID" ]; then echo "no matching process"; exit 1; fi\n'
        f'docker exec {CONTAINER_NAME} kill -9 "$PID"'
    )
    tail_cmd = f"docker exec {CONTAINER_NAME} tail -F {LOGS_DIR_IN_CONTAINER}/{actor['name']}.console.log"
    return {"kill": kill_script, "tail": tail_cmd}


def actor_status(actor):
    """Fetch /stats; non-200 or unreachable -> red; no yellow_threshold_seconds in the response ->
    green; seconds_since_last_recv is null or exceeds the threshold -> yellow; otherwise green.
    Also fetches /log_level and folds it into stats['log_level'] so the dashboard can reflect the
    actor's real current level instead of hardcoding a default."""
    try:
        r = requests.get(f"http://localhost:{actor['command_port']}/stats", timeout=2)
    except Exception:
        return {"status": "red", "stats": None}
    if r.status_code != 200:
        return {"status": "red", "stats": None}
    stats = r.json()
    try:
        lvl_r = requests.get(f"http://localhost:{actor['command_port']}/log_level", timeout=2)
        if lvl_r.status_code == 200:
            stats["log_level"] = lvl_r.json().get("level")
    except Exception:
        pass
    if "yellow_threshold_seconds" not in stats:
        return {"status": "green", "stats": stats}
    since = stats.get("seconds_since_last_recv")
    if since is None or since > stats["yellow_threshold_seconds"]:
        return {"status": "yellow", "stats": stats}
    return {"status": "green", "stats": stats}


def proxy_response(r, content_type="application/json"):
    return (r.content, r.status_code, {"Content-Type": r.headers.get("Content-Type", content_type)})


# --- Routes -----------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/api/actors")
def api_actors():
    return jsonify([
        {
            "name": a["name"],
            "type": a["type"],
            "command_port": a["command_port"],
            "running": is_running(a),
            "is_active": a["is_active"],
            "partner_id": a.get("partner_id"),
        }
        for a in discover_actors()
    ])


@app.route("/api/routers_by_partner")
def api_routers_by_partner():
    result = {}
    for a in discover_actors():
        if a["type"] != "router":
            continue
        key = a.get("partner_id") or "default"
        result.setdefault(key, []).append({"name": a["name"], "command_port": a["command_port"]})
    return jsonify(result)


@app.route("/api/status")
def api_status():
    return jsonify({a["name"]: actor_status(a) for a in discover_actors()})


@app.route("/api/starting")
def api_starting():
    return jsonify({"starting": _starting})


@app.route("/api/csv_files")
def api_csv_files():
    csv_dir = PROJECT_ROOT / "test_csv_files"
    files = []
    if csv_dir.is_dir():
        files = [str(p.relative_to(PROJECT_ROOT)) for p in sorted(csv_dir.glob("*.csv"))]
    return jsonify(files)


@app.route("/api/commands")
def api_commands():
    return jsonify({"shell": f"docker exec -it {CONTAINER_NAME} bash"})


@app.route("/api/actor/<name>/commands")
def api_actor_commands(name):
    actor = get_actor(name)
    if not actor:
        return jsonify({"error": "unknown actor"}), 404
    return jsonify(actor_commands(actor))


@app.route("/api/actor/<name>/launch", methods=["POST"])
def api_actor_launch(name):
    actor = get_actor(name)
    if not actor:
        return jsonify({"error": "unknown actor"}), 404
    if is_running(actor):
        return jsonify({"status": "already running"})
    try:
        launch_actor(actor)
    except subprocess.CalledProcessError as e:
        return jsonify({"error": f"launch failed: {e}"}), 500
    ready = wait_for_ready(actor, timeout=10)
    return jsonify({"status": "ready" if ready else "launched, not yet ready"})


@app.route("/api/actor/<name>/stop", methods=["POST"])
def api_actor_stop(name):
    actor = get_actor(name)
    if not actor:
        return jsonify({"error": "unknown actor"}), 404
    try:
        requests.post(f"http://localhost:{actor['command_port']}/stop",
                     headers=auth_headers(actor), timeout=5)
    except Exception as e:
        return jsonify({"error": f"stop request failed: {e}"}), 500

    deadline = time.time() + 10
    while time.time() < deadline:
        if not is_running(actor):
            return jsonify({"status": "stopped"})
        time.sleep(0.5)
    return jsonify({"status": "stop requested, still running"}), 202


@app.route("/api/actor/<name>/stats")
def api_actor_stats(name):
    actor = get_actor(name)
    if not actor:
        return jsonify({"error": "unknown actor"}), 404
    try:
        r = requests.get(f"http://localhost:{actor['command_port']}/stats", timeout=3)
    except Exception as e:
        return jsonify({"error": str(e)}), 502
    return proxy_response(r)


@app.route("/api/actor/<name>/start")
def api_actor_start(name):
    actor = get_actor(name)
    if not actor or actor["type"] != "upstream":
        return jsonify({"error": "not an upstream actor"}), 404
    try:
        r = requests.get(f"http://localhost:{actor['command_port']}/start", timeout=5)
    except Exception as e:
        return jsonify({"error": str(e)}), 502
    return proxy_response(r)


@app.route("/api/actor/<name>/results")
def api_actor_results(name):
    actor = get_actor(name)
    if not actor or actor["type"] != "upstream":
        return jsonify({"error": "not an upstream actor"}), 404
    try:
        r = requests.get(f"http://localhost:{actor['command_port']}/results", timeout=5)
    except Exception as e:
        return jsonify({"error": str(e)}), 502
    return proxy_response(r)


@app.route("/api/actor/<name>/log_level", methods=["GET", "POST"])
def api_actor_log_level(name):
    actor = get_actor(name)
    if not actor:
        return jsonify({"error": "unknown actor"}), 404
    url = f"http://localhost:{actor['command_port']}/log_level"
    try:
        if request.method == "POST":
            body = request.get_json(force=True, silent=True) or {}
            r = requests.post(url, json=body, headers=auth_headers(actor), timeout=5)
        else:
            r = requests.get(url, timeout=5)
    except Exception as e:
        return jsonify({"error": str(e)}), 502
    return proxy_response(r)


@app.route("/api/actor/<name>/logs")
def api_actor_logs(name):
    actor = get_actor(name)
    if not actor:
        return jsonify({"error": "unknown actor"}), 404
    fmt = request.args.get("format")
    try:
        r = requests.get(f"http://localhost:{actor['command_port']}/logs",
                         params={"format": fmt} if fmt else None, timeout=5)
    except Exception as e:
        return jsonify({"error": str(e)}), 502
    return proxy_response(r, content_type="text/plain" if fmt == "text" else "application/json")


@app.route("/api/actor/<name>/upload", methods=["POST"])
def api_actor_upload(name):
    actor = get_actor(name)
    if not actor or actor["type"] != "upstream":
        return jsonify({"error": "not an upstream actor"}), 404
    if "file" not in request.files:
        return jsonify({"error": "missing 'file' part"}), 400
    f = request.files["file"]
    try:
        r = requests.post(
            f"http://localhost:{actor['command_port']}/upload",
            files={"file": (f.filename, f.stream, f.content_type)},
            timeout=10,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 502
    return proxy_response(r)


@app.route("/api/actor/<name>/upload_path", methods=["POST"])
def api_actor_upload_path(name):
    actor = get_actor(name)
    if not actor or actor["type"] != "upstream":
        return jsonify({"error": "not an upstream actor"}), 404
    body = request.get_json(force=True, silent=True) or {}
    rel_path = body.get("path")
    if not rel_path:
        return jsonify({"error": "missing 'path'"}), 400

    file_path = (PROJECT_ROOT / rel_path).resolve()
    if not file_path.is_relative_to(PROJECT_ROOT):
        return jsonify({"error": "path escapes project root"}), 400
    if not file_path.is_file():
        return jsonify({"error": f"file not found: {rel_path}"}), 404

    try:
        with open(file_path, "rb") as fh:
            r = requests.post(
                f"http://localhost:{actor['command_port']}/upload",
                files={"file": (file_path.name, fh, "text/csv")},
                timeout=10,
            )
    except Exception as e:
        return jsonify({"error": str(e)}), 502
    return proxy_response(r)


@app.route("/api/actor/<name>/dispatcher/purge", methods=["POST"])
def api_actor_purge(name):
    actor = get_actor(name)
    if not actor or actor["type"] != "router":
        return jsonify({"error": "not a router actor"}), 404
    try:
        r = requests.post(f"http://localhost:{actor['command_port']}/dispatcher/purge",
                         headers=auth_headers(actor), timeout=5)
    except Exception as e:
        return jsonify({"error": str(e)}), 502
    return proxy_response(r)


def _start_all_worker():
    global _starting
    try:
        actors = sorted(discover_actors(), key=lambda a: STARTUP_ORDER.get(a["type"], 99))
        for actor in actors:
            if not actor["is_active"] or is_running(actor):
                continue
            try:
                launch_actor(actor)
            except Exception:
                continue
            wait_for_ready(actor, timeout=10)
    finally:
        _starting = False


@app.route("/api/start_all", methods=["POST"])
def api_start_all():
    global _starting
    with _starting_lock:
        if _starting:
            return jsonify({"status": "already starting"}), 409
        _starting = True
    threading.Thread(target=_start_all_worker, daemon=True).start()
    return jsonify({"status": "starting"})


@app.route("/api/stop_all", methods=["POST"])
def api_stop_all():
    actors = sorted(discover_actors(), key=lambda a: STARTUP_ORDER.get(a["type"], 99), reverse=True)
    results = {}
    for actor in actors:
        if not is_running(actor):
            results[actor["name"]] = "not running"
            continue
        try:
            requests.post(f"http://localhost:{actor['command_port']}/stop",
                         headers=auth_headers(actor), timeout=5)
            results[actor["name"]] = "stop requested"
        except Exception as e:
            results[actor["name"]] = f"error: {e}"
    return jsonify(results)


def _shutdown_worker():
    for actor in discover_actors():
        try:
            if is_running(actor):
                requests.post(f"http://localhost:{actor['command_port']}/stop",
                             headers=auth_headers(actor), timeout=3)
        except Exception:
            pass
    time.sleep(0.3)
    os._exit(0)


@app.route("/stop", methods=["POST"])
def api_stop_monitor():
    """Best-effort /stop to every running actor first, then exit. No process handle to fall back
    on if an actor ignores /stop -- ./stop.sh (docker compose down) is the hard backstop."""
    threading.Thread(target=_shutdown_worker, daemon=True).start()
    return jsonify({"status": "stopping"})


def main():
    app.run(host="0.0.0.0", port=8090, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()

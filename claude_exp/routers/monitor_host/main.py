#!/usr/bin/env python3
"""Shared monitor dashboard for router_py/router_java/router_cpp - one Flask app + one set of
actor-lifecycle plumbing, instead of the ~1700 duplicated lines that used to live as
router_py/monitor/, router_java/monitor/, router_cpp/monitor/ (each its own copy). Runs in its
own container (see monitor_host/Dockerfile/start.sh) rather than on the host - --network host and
a bind-mount of the whole routers/ tree keep it behaving exactly like the three host-run
processes it replaces: localhost:<port> reachability is unchanged, and it can still `docker exec`
into router_java's/router_cpp's containers (docker.sock is mounted in) or spawn host subprocesses
for router_py's own actors and the shared upstream_host/downstream_host components.

Consolidated 2026-08-17: this pass keeps every backend's *current* feature set rather than
unifying the UI (router_py's had partner grouping/infra group/Pending/Trace/log-level/purge that
router_java/router_cpp's UIs don't; router_java's had a commands drawer that router_py's doesn't;
router_cpp's was the thinnest of the three). See routers/briefs/old/... history and
routers/to_do_java_cpp.md for that background - the actual UI redesign is still a separate,
not-yet-decided piece of work. This file exposes the *union* of routes so nothing regresses, but
each target's static/<target>/index.html is carried over unmodified and only calls what it always
called - unused routes are harmless, not a half-finished feature.

Backend contract (see backends/router_py.py, backends/router_java.py, backends/router_cpp.py):
  CONTAINER_NAME: str | None          - docker container name for this target, None if none
  HOST_SUBPROCESS_TYPES: set[str]     - actor types launched as host subprocesses, not docker exec
  discover_actors() -> list[dict]     - each actor: name, type, command_port, is_active,
                                         partner_id (may be None), auth_token (may be None), plus
                                         whatever launch needs (config_path, or
                                         config_abs_path_in_container + binary for docker-exec
                                         types)
  host_subprocess_cmd(actor) -> (argv: list[str], cwd: str)  - only called for
                                         actor["type"] in HOST_SUBPROCESS_TYPES
  launch_docker_actor(actor) -> None  - `docker exec -d ...`, only called otherwise
  docker_actor_commands(actor) -> {"kill": str, "tail": str}  - only called otherwise
"""
import argparse
import importlib
import logging
import os
import subprocess
import threading
import time

import requests
from flask import Flask, jsonify, request, send_from_directory

MONITOR_HOST_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_ROOT = os.path.join(MONITOR_HOST_DIR, "static")
VALID_TARGETS = ("router_py", "router_java", "router_cpp")

logger = logging.getLogger(__name__)

backend = None  # set in main(), a module from backends/

_actors_cache = None
_actors_lock = threading.Lock()

_processes = {}
_processes_lock = threading.Lock()

_starting = False
_starting_lock = threading.Lock()

_starting_partners = set()
_starting_partners_lock = threading.Lock()

_INFRA_KEY = "__infra__"


def discover_actors():
    global _actors_cache
    with _actors_lock:
        if _actors_cache is None:
            _actors_cache = backend.discover_actors()
        return _actors_cache


def get_actor(name):
    return next((a for a in discover_actors() if a["name"] == name), None)


def _actors_for_partner(partner_id):
    return [a for a in discover_actors() if a["partner_id"] == partner_id]


def _supporting_actors():
    # crypto_host + downstream_host, typically - any actor with no partner_id at all.
    return [a for a in discover_actors() if not a["partner_id"]]


def auth_headers(actor):
    token = actor.get("auth_token")
    return {"X-Router-Auth": token} if token else {}


def is_running(name):
    """No process handle to poll for docker-exec'd actors -- docker exec -d's client exits
    immediately once the detached command starts. Liveness is "the actor's own /stats endpoint
    answers HTTP 200" uniformly, whether the actor is a real Popen'd host subprocess or not."""
    actor = get_actor(name)
    if actor is None:
        return False
    try:
        resp = requests.get(f"http://127.0.0.1:{actor['command_port']}/stats", timeout=1)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def wait_for_ready(actor, timeout=10):
    """Polls /stats until the actor answers 200, and - for router/upstream - until its
    downstream/router connection is up. Without the connection check, a /start called
    immediately after "Start All" can 503 with "not connected to router" even though every
    /stats already answers 200. Returns True once ready, False on timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(f"http://127.0.0.1:{actor['command_port']}/stats", timeout=1)
            if resp.status_code == 200:
                connections = resp.json().get("connections", {})
                if actor["type"] == "router":
                    if connections.get("downstream"):
                        return True
                elif actor["type"] == "upstream":
                    if connections.get("router"):
                        return True
                else:
                    return True
        except Exception:
            pass
        time.sleep(0.3)
    logger.warning("wait_for_ready timed out for %s", actor["name"])
    return False


def launch_actor(actor):
    if actor["type"] in backend.HOST_SUBPROCESS_TYPES:
        argv, cwd = backend.host_subprocess_cmd(actor)
        proc = subprocess.Popen(argv, cwd=cwd)
        with _processes_lock:
            _processes[actor["name"]] = proc
        logger.info("launched %s as host subprocess (pid=%s)", actor["name"], proc.pid)
    else:
        backend.launch_docker_actor(actor)
        logger.info("launched %s via docker exec (%s)", actor["name"], backend.CONTAINER_NAME)


def stop_actor(actor):
    try:
        requests.post(
            f"http://127.0.0.1:{actor['command_port']}/stop", headers=auth_headers(actor), timeout=3
        )
    except requests.RequestException:
        pass
    # No process handle to wait() on for docker-exec'd actors; poll HTTP liveness instead so
    # callers don't report success before the process has actually exited.
    deadline = time.time() + 10
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


def actor_commands(actor):
    if actor["type"] in backend.HOST_SUBPROCESS_TYPES:
        with _processes_lock:
            proc = _processes.get(actor["name"])
        if proc is not None:
            kill = f"kill -9 {proc.pid}"
        else:
            argv, _cwd = backend.host_subprocess_cmd(actor)
            kill = f'pkill -f "{" ".join(argv)}"'
        return {
            "kill": kill,
            "tail": "(no log file - host subprocess with inherited stdout/stderr)",
        }
    return backend.docker_actor_commands(actor)


def _start_actors(actors):
    for actor in actors:
        if not actor["is_active"]:
            continue
        if not is_running(actor["name"]):
            launch_actor(actor)
        wait_for_ready(actor, timeout=10)


def _start_all_worker():
    global _starting
    try:
        _start_actors(discover_actors())
    finally:
        with _starting_lock:
            _starting = False


def _start_partner_worker(partner_id):
    with _starting_partners_lock:
        _starting_partners.add(partner_id)
    try:
        _start_actors(_actors_for_partner(partner_id))
    finally:
        with _starting_partners_lock:
            _starting_partners.discard(partner_id)


def _start_infra_worker():
    with _starting_partners_lock:
        _starting_partners.add(_INFRA_KEY)
    try:
        _start_actors(_supporting_actors())
    finally:
        with _starting_partners_lock:
            _starting_partners.discard(_INFRA_KEY)


def _terminate_all():
    with _processes_lock:
        procs = list(_processes.values())
    for proc in procs:
        try:
            proc.terminate()
        except Exception:
            pass
    for proc in procs:
        try:
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _actor_status(actor):
    """Fetch /stats; non-200 or unreachable -> red; no yellow_threshold_seconds in the response ->
    green; seconds_since_last_recv is null or exceeds the threshold -> yellow; otherwise green.
    Also folds /log_level into stats['log_level'] when available."""
    try:
        r = requests.get(f"http://127.0.0.1:{actor['command_port']}/stats", timeout=2)
    except Exception:
        return {"status": "red", "stats": None}
    if r.status_code != 200:
        return {"status": "red", "stats": None}
    stats = r.json()
    try:
        lvl_r = requests.get(f"http://127.0.0.1:{actor['command_port']}/log_level", timeout=2)
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


def _proxy_get(name, path):
    actor = get_actor(name)
    if not actor:
        return jsonify({"error": "not found"}), 404
    try:
        resp = requests.get(
            f"http://127.0.0.1:{actor['command_port']}/{path}", headers=auth_headers(actor), timeout=5
        )
        return resp.text, resp.status_code, {"Content-Type": resp.headers.get("Content-Type", "application/json")}
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502


def _proxy_post(name, path, json_body=None):
    actor = get_actor(name)
    if not actor:
        return jsonify({"error": "not found"}), 404
    try:
        resp = requests.post(
            f"http://127.0.0.1:{actor['command_port']}/{path}",
            json=json_body,
            headers=auth_headers(actor),
            timeout=5,
        )
        return resp.text, resp.status_code, {"Content-Type": resp.headers.get("Content-Type", "application/json")}
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502


def _make_app(target):
    app = Flask(__name__, static_folder=None)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    static_dir = os.path.join(STATIC_ROOT, target)

    @app.route("/")
    def index():
        return send_from_directory(static_dir, "index.html")

    @app.route("/api/actors")
    def actors():
        return jsonify([
            {
                "name": a["name"],
                "type": a["type"],
                "command_port": a["command_port"],
                "running": is_running(a["name"]),
                "is_active": a["is_active"],
                "partner_id": a.get("partner_id"),
            }
            for a in discover_actors()
        ])

    @app.route("/api/actors_by_partner")
    def actors_by_partner():
        result = {}
        for a in discover_actors():
            if not a.get("partner_id"):
                continue
            result.setdefault(a["partner_id"], []).append(
                {"name": a["name"], "type": a["type"], "command_port": a["command_port"]}
            )
        return jsonify(result)

    @app.route("/api/routers_by_partner")
    def routers_by_partner():
        result = {}
        for a in discover_actors():
            if a["type"] != "router":
                continue
            key = a.get("partner_id") or "default"
            result.setdefault(key, []).append({"name": a["name"], "command_port": a["command_port"]})
        return jsonify(result)

    @app.route("/api/status")
    def status():
        result = {}
        lock = threading.Lock()

        def worker(actor):
            s = _actor_status(actor)
            with lock:
                result[actor["name"]] = s

        threads = [threading.Thread(target=worker, args=(a,)) for a in discover_actors()]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        return jsonify(result)

    @app.route("/api/starting")
    def starting():
        with _starting_lock:
            return jsonify({"starting": _starting})

    @app.route("/api/csv_files")
    def csv_files():
        files = []
        project_root = getattr(backend, "PROJECT_ROOT", None)
        if project_root is None:
            return jsonify(files)
        test_dir = os.path.join(project_root, "test_csv_files")
        if os.path.isdir(test_dir):
            for fn in sorted(os.listdir(test_dir)):
                if fn.endswith(".csv"):
                    files.append(os.path.relpath(os.path.join(test_dir, fn), project_root))
        for a in discover_actors():
            if a["type"] != "upstream":
                continue
            config_path = a.get("config_path")
            if not config_path:
                continue
            input_dir = os.path.join(os.path.dirname(config_path), "input")
            if os.path.isdir(input_dir):
                for fn in sorted(os.listdir(input_dir)):
                    if fn.endswith(".csv"):
                        files.append(os.path.relpath(os.path.join(input_dir, fn), project_root))
        return jsonify(files)

    @app.route("/api/commands")
    def commands():
        if backend.CONTAINER_NAME:
            return jsonify({"shell": f"docker exec -it {backend.CONTAINER_NAME} bash"})
        return jsonify({"shell": None})

    @app.route("/api/actor/<name>/commands")
    def api_actor_commands(name):
        actor = get_actor(name)
        if not actor:
            return jsonify({"error": "unknown actor"}), 404
        return jsonify(actor_commands(actor))

    @app.route("/api/actor/<name>/launch", methods=["POST"])
    def actor_launch(name):
        actor = get_actor(name)
        if not actor:
            return jsonify({"error": "not found"}), 404
        if is_running(name):
            return jsonify({"status": "already running"})
        try:
            launch_actor(actor)
        except subprocess.CalledProcessError as e:
            return jsonify({"error": f"launch failed: {e}"}), 500
        ready = wait_for_ready(actor, timeout=10)
        return jsonify({"status": "ready" if ready else "launched, not yet ready"})

    @app.route("/api/actor/<name>/stop", methods=["POST"])
    def actor_stop(name):
        actor = get_actor(name)
        if not actor:
            return jsonify({"error": "not found"}), 404
        stop_actor(actor)
        return jsonify({"status": "stopped"})

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

    @app.route("/api/actor/<name>/pending")
    def actor_pending(name):
        return _proxy_get(name, "pending")

    @app.route("/api/actor/<name>/trace", methods=["GET", "POST"])
    def actor_trace(name):
        if request.method == "POST":
            return _proxy_post(name, "trace", json_body=request.json)
        return _proxy_get(name, "trace")

    @app.route("/api/actor/<name>/upload", methods=["POST"])
    def actor_upload(name):
        actor = get_actor(name)
        if not actor:
            return jsonify({"error": "not found"}), 404
        try:
            f = request.files.get("file")
            if f is None:
                return jsonify({"error": "no file"}), 400
            resp = requests.post(
                f"http://127.0.0.1:{actor['command_port']}/upload",
                files={"file": (f.filename, f.read(), f.content_type)},
                headers=auth_headers(actor),
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
        project_root = getattr(backend, "PROJECT_ROOT", None)
        body = request.json or {}
        rel_path = body.get("path", "")
        abs_path = os.path.normpath(os.path.join(project_root, rel_path)) if project_root else rel_path
        if not os.path.exists(abs_path):
            return jsonify({"error": "file not found"}), 404
        with open(abs_path, "rb") as f:
            content = f.read()
        try:
            resp = requests.post(
                f"http://127.0.0.1:{actor['command_port']}/upload",
                files={"file": (os.path.basename(abs_path), content, "text/csv")},
                headers=auth_headers(actor),
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
                return jsonify({"status": "already starting"}), 409
            _starting = True
        threading.Thread(target=_start_all_worker, daemon=True).start()
        return jsonify({"status": "starting"})

    @app.route("/api/stop_all", methods=["POST"])
    def stop_all():
        for a in reversed(discover_actors()):
            if is_running(a["name"]):
                stop_actor(a)
        return jsonify({"status": "stopped"})

    @app.route("/api/partner/<partner_id>/start", methods=["POST"])
    def partner_start(partner_id):
        with _starting_partners_lock:
            if partner_id in _starting_partners:
                return jsonify({"status": "already starting"})
        threading.Thread(target=_start_partner_worker, args=(partner_id,), daemon=True).start()
        return jsonify({"status": "starting"})

    @app.route("/api/partner/<partner_id>/stop", methods=["POST"])
    def partner_stop(partner_id):
        for a in reversed(_actors_for_partner(partner_id)):
            if is_running(a["name"]):
                stop_actor(a)
        return jsonify({"status": "stopped"})

    @app.route("/api/partner/<partner_id>/starting")
    def partner_starting(partner_id):
        with _starting_partners_lock:
            return jsonify({"starting": partner_id in _starting_partners})

    @app.route("/api/infra/start", methods=["POST"])
    def infra_start():
        with _starting_partners_lock:
            if _INFRA_KEY in _starting_partners:
                return jsonify({"status": "already starting"})
        threading.Thread(target=_start_infra_worker, daemon=True).start()
        return jsonify({"status": "starting"})

    @app.route("/api/infra/stop", methods=["POST"])
    def infra_stop():
        for a in reversed(_supporting_actors()):
            if is_running(a["name"]):
                stop_actor(a)
        return jsonify({"status": "stopped"})

    @app.route("/api/infra/starting")
    def infra_starting():
        with _starting_partners_lock:
            return jsonify({"starting": _INFRA_KEY in _starting_partners})

    @app.route("/stop", methods=["POST"])
    def stop_monitor():
        # Containerized now, so `docker stop` (see stop.sh) is the normal path - this route stays
        # for API compatibility with the three UIs, which all still call it.
        def _shutdown():
            time.sleep(0.2)
            _terminate_all()
            os._exit(0)

        threading.Thread(target=_shutdown, daemon=True).start()
        return jsonify({"status": "stopping"})

    return app


def main():
    global backend

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument(
        "--target",
        choices=VALID_TARGETS,
        default=os.environ.get("MONITOR_TARGET"),
        help="Which implementation to monitor (or set MONITOR_TARGET)",
    )
    args = parser.parse_args()

    if not args.target:
        parser.error("--target is required (or set MONITOR_TARGET)")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    backend = importlib.import_module(f"backends.{args.target}")

    app = _make_app(args.target)
    logger.info("monitor listening on port %d, target=%s", args.port, args.target)
    app.run(host="0.0.0.0", port=args.port, use_reloader=False)


if __name__ == "__main__":
    main()

import argparse
import atexit
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time

import requests
from flask import Flask, jsonify, request, send_from_directory

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCRIPTS_BY_TYPE = {
    "router": "router/main.py",
    "upstream": "simulators/upstream_host/main.py",
    "downstream": "simulators/downstream_host/main.py",
    "crypto": "simulators/crypto_host/main.py",
}
CONFIG_REQUIRED_TYPES = {"router", "upstream"}
STARTUP_ORDER = {"crypto": 0, "downstream": 1, "router": 2, "upstream": 3}

logger = logging.getLogger(__name__)

_actors_cache = None
_actors_lock = threading.Lock()

_processes = {}
_processes_lock = threading.Lock()

_starting = False
_starting_lock = threading.Lock()


def discover_actors():
    global _actors_cache
    with _actors_lock:
        if _actors_cache is not None:
            return _actors_cache

        found = []
        for root, dirs, files in os.walk(PROJECT_ROOT):
            dirs[:] = [d for d in dirs if d != "monitor" and d != "__pycache__" and not d.startswith(".")]
            if "config.json" not in files:
                continue
            path = os.path.join(root, "config.json")
            try:
                with open(path) as f:
                    cfg = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue

            name = cfg.get("name")
            actor_type = cfg.get("type")
            if not name or actor_type not in SCRIPTS_BY_TYPE:
                continue

            found.append(
                {
                    "name": name,
                    "type": actor_type,
                    "command_port": cfg.get("command_port"),
                    "config_path": path,
                    "is_active": cfg.get("is_active", True),
                }
            )

        found.sort(key=lambda a: STARTUP_ORDER.get(a["type"], 99))
        _actors_cache = found
        return _actors_cache


def get_actors():
    return discover_actors()


def get_actor(name):
    return next((a for a in get_actors() if a["name"] == name), None)


def is_running(name):
    with _processes_lock:
        proc = _processes.get(name)
    return proc is not None and proc.poll() is None


def launch_actor(actor):
    script = os.path.join(PROJECT_ROOT, SCRIPTS_BY_TYPE[actor["type"]])
    cmd = [sys.executable, script]
    if actor["type"] in CONFIG_REQUIRED_TYPES:
        cmd += ["--config", actor["config_path"]]
    proc = subprocess.Popen(cmd, cwd=PROJECT_ROOT)
    with _processes_lock:
        _processes[actor["name"]] = proc
    logger.info("launched %s (pid=%s)", actor["name"], proc.pid)


def stop_actor(actor):
    try:
        requests.post(f"http://127.0.0.1:{actor['command_port']}/stop", timeout=3)
    except requests.RequestException:
        pass
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
            input_dir = os.path.join(os.path.dirname(a["config_path"]), "input")
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

    # Both an atexit handler AND an explicit SIGTERM handler are required: Python's atexit
    # handlers do not run on a bare SIGTERM (only on normal interpreter exit), so without the
    # signal handler, `kill <pid>` orphans every actor subprocess.
    atexit.register(_terminate_all)

    def _handle_sigterm(_signum, _frame):
        _terminate_all()
        os._exit(0)

    signal.signal(signal.SIGTERM, _handle_sigterm)

    app = _make_app(args.port)
    logger.info("monitor listening on port %d", args.port)
    app.run(host="0.0.0.0", port=args.port, use_reloader=False)


if __name__ == "__main__":
    main()

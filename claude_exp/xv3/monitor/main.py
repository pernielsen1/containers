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
from glob import glob

import requests
from flask import Flask, jsonify, request, send_from_directory

logging.getLogger("werkzeug").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

SCRIPTS_BY_TYPE = {
    "router": "router/main.py",
    "upstream": "simulators/upstream_host/main.py",
    "downstream": "simulators/downstream_host/main.py",
    "crypto": "simulators/crypto_host/main.py",
}
CONFIG_REQUIRED_TYPES = {"router", "upstream"}
STARTUP_ORDER = {"crypto": 0, "downstream": 1, "router": 2, "upstream": 3}

app = Flask(__name__, static_folder=None)

_processes = {}
_processes_lock = threading.Lock()
_actors_cache = None
_starting = False
_starting_lock = threading.Lock()


def discover_actors():
    actors = []
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]

        rel_root = os.path.relpath(root, PROJECT_ROOT)
        parts = [] if rel_root == "." else rel_root.split(os.sep)
        if parts and parts[0] == "monitor":
            dirs[:] = []
            continue

        if "config.json" not in files:
            continue

        config_path = os.path.join(root, "config.json")
        try:
            with open(config_path) as f:
                cfg = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue

        name = cfg.get("name")
        actor_type = cfg.get("type")
        if not name or actor_type not in SCRIPTS_BY_TYPE:
            continue

        actors.append(
            {
                "name": name,
                "type": actor_type,
                "command_port": cfg.get("command_port"),
                "config_path": config_path,
                "config": cfg,
                "script": os.path.join(PROJECT_ROOT, SCRIPTS_BY_TYPE[actor_type]),
                "is_active": cfg.get("is_active", True),
            }
        )

    actors.sort(key=lambda a: (STARTUP_ORDER.get(a["type"], 99), a["name"]))
    return actors


def get_actors():
    global _actors_cache
    if _actors_cache is None:
        _actors_cache = discover_actors()
    return _actors_cache


def get_actor(name):
    for actor in get_actors():
        if actor["name"] == name:
            return actor
    return None


def is_running(name) -> bool:
    with _processes_lock:
        popen = _processes.get(name)
    return popen is not None and popen.poll() is None


def launch_actor(actor) -> bool:
    if is_running(actor["name"]):
        return False
    args = [sys.executable, actor["script"]]
    if actor["type"] in CONFIG_REQUIRED_TYPES:
        args += ["--config", actor["config_path"]]
    popen = subprocess.Popen(args, cwd=PROJECT_ROOT)
    with _processes_lock:
        _processes[actor["name"]] = popen
    return True


# For these actor types, "ready" means more than the command server responding — the actor's
# own TCP link to its peer must be up too, or a /start called immediately afterward (e.g. from
# the monitor UI right after Start All finishes) can 503 with "not connected to router" even
# though every /stats endpoint already answered 200.
_READY_CONNECTION_KEY = {"router": "downstream", "upstream": "router"}


def wait_for_ready(actor, timeout=10) -> bool:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{actor['command_port']}/stats"
    connection_key = _READY_CONNECTION_KEY.get(actor["type"])
    while time.monotonic() < deadline:
        try:
            resp = requests.get(url, timeout=1)
            if resp.status_code == 200:
                if connection_key is None:
                    return True
                if resp.json().get("connections", {}).get(connection_key):
                    return True
        except requests.RequestException:
            pass
        time.sleep(0.3)
    return False


def auth_headers(actor) -> dict:
    token = actor["config"].get("command_auth_token")
    return {"X-Router-Auth": token} if token else {}


def proxy_get(actor, path, params=None):
    url = f"http://127.0.0.1:{actor['command_port']}{path}"
    return requests.get(url, params=params, timeout=5)


def proxy_post(actor, path, protected=False, **kwargs):
    url = f"http://127.0.0.1:{actor['command_port']}{path}"
    headers = kwargs.pop("headers", {}) or {}
    if protected:
        headers.update(auth_headers(actor))
    return requests.post(url, headers=headers, timeout=10, **kwargs)


def _relay(resp):
    content_type = resp.headers.get("Content-Type", "application/json")
    return resp.content, resp.status_code, {"Content-Type": content_type}


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/api/actors")
def api_actors():
    return jsonify(
        [
            {
                "name": a["name"],
                "type": a["type"],
                "command_port": a["command_port"],
                "running": is_running(a["name"]),
                "is_active": a["is_active"],
            }
            for a in get_actors()
        ]
    )


@app.route("/api/routers_by_partner")
def api_routers_by_partner():
    grouped = {}
    for actor in get_actors():
        if actor["type"] != "router":
            continue
        partner_id = actor["config"].get("partner_id", "unknown")
        grouped.setdefault(partner_id, []).append(
            {"name": actor["name"], "command_port": actor["command_port"]}
        )
    return jsonify(grouped)


def _actor_status(actor) -> str:
    if not is_running(actor["name"]):
        return "red"
    try:
        resp = requests.get(f"http://127.0.0.1:{actor['command_port']}/stats", timeout=2)
        resp.raise_for_status()
        stats = resp.json()
    except requests.RequestException:
        return "red"

    threshold = stats.get("yellow_threshold_seconds")
    if threshold is None:
        return "green"
    seconds_since = stats.get("seconds_since_last_recv")
    if seconds_since is None or seconds_since > threshold:
        return "yellow"
    return "green"


@app.route("/api/status")
def api_status():
    actors = get_actors()
    result = {}
    lock = threading.Lock()

    def worker(actor):
        status = _actor_status(actor)
        with lock:
            result[actor["name"]] = {"status": status, "running": is_running(actor["name"])}

    threads = [threading.Thread(target=worker, args=(actor,)) for actor in actors]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    return jsonify(result)


@app.route("/api/starting")
def api_starting():
    with _starting_lock:
        return jsonify({"starting": _starting})


@app.route("/api/csv_files")
def api_csv_files():
    files = []
    for path in sorted(glob(os.path.join(PROJECT_ROOT, "test_csv_files", "*.csv"))):
        files.append(os.path.relpath(path, PROJECT_ROOT).replace(os.sep, "/"))

    for actor in get_actors():
        if actor["type"] != "upstream":
            continue
        input_dir = actor["config"].get("input_dir", "input")
        abs_input_dir = os.path.normpath(os.path.join(os.path.dirname(actor["config_path"]), input_dir))
        for path in sorted(glob(os.path.join(abs_input_dir, "*.csv"))):
            files.append(os.path.relpath(path, PROJECT_ROOT).replace(os.sep, "/"))

    return jsonify(files)


@app.route("/api/actor/<name>/launch", methods=["POST"])
def api_launch(name):
    actor = get_actor(name)
    if actor is None:
        return jsonify({"error": "unknown actor"}), 404
    started = launch_actor(actor)
    return jsonify({"started": started})


@app.route("/api/actor/<name>/stop", methods=["POST"])
def api_stop(name):
    actor = get_actor(name)
    if actor is None:
        return jsonify({"error": "unknown actor"}), 404
    try:
        return _relay(proxy_post(actor, "/stop", protected=True))
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/actor/<name>/stats", methods=["GET"])
def api_stats(name):
    actor = get_actor(name)
    if actor is None:
        return jsonify({"error": "unknown actor"}), 404
    try:
        return _relay(proxy_get(actor, "/stats"))
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/actor/<name>/start", methods=["GET"])
def api_start(name):
    actor = get_actor(name)
    if actor is None or actor["type"] != "upstream":
        return jsonify({"error": "unknown upstream actor"}), 404
    try:
        return _relay(proxy_get(actor, "/start"))
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/actor/<name>/results", methods=["GET"])
def api_results(name):
    actor = get_actor(name)
    if actor is None:
        return jsonify({"error": "unknown actor"}), 404
    try:
        return _relay(proxy_get(actor, "/results"))
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/actor/<name>/log_level", methods=["GET", "POST"])
def api_log_level(name):
    actor = get_actor(name)
    if actor is None:
        return jsonify({"error": "unknown actor"}), 404
    try:
        if request.method == "POST":
            resp = proxy_post(actor, "/log_level", protected=True, json=request.get_json(silent=True))
        else:
            resp = proxy_get(actor, "/log_level")
        return _relay(resp)
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/actor/<name>/logs", methods=["GET"])
def api_logs(name):
    actor = get_actor(name)
    if actor is None:
        return jsonify({"error": "unknown actor"}), 404
    try:
        fmt = request.args.get("format")
        params = {"format": fmt} if fmt else None
        return _relay(proxy_get(actor, "/logs", params=params))
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/actor/<name>/upload", methods=["POST"])
def api_upload(name):
    actor = get_actor(name)
    if actor is None:
        return jsonify({"error": "unknown actor"}), 404
    uploaded = request.files.get("file")
    if uploaded is None:
        return jsonify({"error": "no file provided"}), 400
    try:
        url = f"http://127.0.0.1:{actor['command_port']}/upload"
        resp = requests.post(
            url, files={"file": (uploaded.filename, uploaded.stream, uploaded.mimetype)}, timeout=10
        )
        return _relay(resp)
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/actor/<name>/upload_path", methods=["POST"])
def api_upload_path(name):
    actor = get_actor(name)
    if actor is None:
        return jsonify({"error": "unknown actor"}), 404

    body = request.get_json(silent=True) or {}
    rel_path = body.get("path")
    if not rel_path:
        return jsonify({"error": "path is required"}), 400

    abs_path = os.path.normpath(os.path.join(PROJECT_ROOT, rel_path))
    if not (abs_path == PROJECT_ROOT or abs_path.startswith(PROJECT_ROOT + os.sep)):
        return jsonify({"error": "path escapes project root"}), 400
    if not os.path.isfile(abs_path):
        return jsonify({"error": "file not found"}), 404

    try:
        with open(abs_path, "rb") as f:
            url = f"http://127.0.0.1:{actor['command_port']}/upload"
            resp = requests.post(url, files={"file": (os.path.basename(abs_path), f, "text/csv")}, timeout=10)
        return _relay(resp)
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/actor/<name>/dispatcher/purge", methods=["POST"])
def api_purge(name):
    actor = get_actor(name)
    if actor is None or actor["type"] != "router":
        return jsonify({"error": "unknown router actor"}), 404
    try:
        return _relay(proxy_post(actor, "/dispatcher/purge", protected=True))
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502


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


@app.route("/api/start_all", methods=["POST"])
def api_start_all():
    global _starting
    with _starting_lock:
        if _starting:
            return jsonify({"status": "already starting"}), 409
        _starting = True
    threading.Thread(target=_start_all_worker, daemon=True).start()
    return jsonify({"status": "starting"})


def _reap_processes(timeout=5):
    deadline = time.monotonic() + timeout
    with _processes_lock:
        items = list(_processes.items())
    for _name, popen in items:
        remaining = max(0, deadline - time.monotonic())
        try:
            popen.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            popen.terminate()
            try:
                popen.wait(timeout=2)
            except subprocess.TimeoutExpired:
                popen.kill()


@app.route("/api/stop_all", methods=["POST"])
def api_stop_all():
    for actor in reversed(get_actors()):
        if not is_running(actor["name"]):
            continue
        try:
            proxy_post(actor, "/stop", protected=True)
        except requests.RequestException:
            pass
    _reap_processes(timeout=5)
    return jsonify({"status": "stopped"})


def _terminate_all_processes():
    with _processes_lock:
        items = list(_processes.items())
    for _name, popen in items:
        if popen.poll() is None:
            popen.terminate()
    for _name, popen in items:
        try:
            popen.wait(timeout=3)
        except subprocess.TimeoutExpired:
            popen.kill()


atexit.register(_terminate_all_processes)


def _handle_sigterm(signum, frame):
    # atexit handlers do not run on a bare SIGTERM, only on normal interpreter
    # exit — without this, killing the monitor process (kill <pid>, docker
    # stop, systemd stop, ...) orphans every actor it spawned.
    _terminate_all_processes()
    os._exit(0)


signal.signal(signal.SIGTERM, _handle_sigterm)


@app.route("/stop", methods=["POST"])
def stop_monitor():
    _terminate_all_processes()
    threading.Timer(0.3, lambda: os._exit(0)).start()
    return jsonify({"status": "stopping"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app.run(host="127.0.0.1", port=args.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()

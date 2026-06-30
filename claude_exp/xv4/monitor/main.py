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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from flask import Flask, jsonify, request, send_from_directory

logger = logging.getLogger(__name__)

SCRIPTS_BY_TYPE = {
    "router": "router/main.py",
    "upstream": "simulators/upstream_host/main.py",
    "downstream": "simulators/downstream_host/main.py",
    "crypto": "simulators/crypto_host/main.py",
}

STARTUP_ORDER = {"crypto": 0, "downstream": 1, "router": 2, "upstream": 3}
NEEDS_CONFIG = {"router", "upstream"}

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_actors = None
_actors_lock = threading.Lock()
_processes = {}
_processes_lock = threading.Lock()
_starting = False
_starting_lock = threading.Lock()


def discover_actors():
    global _actors
    with _actors_lock:
        if _actors is not None:
            return _actors

    found = []
    for dirpath, dirnames, filenames in os.walk(PROJECT_ROOT):
        # Skip monitor directory
        rel = os.path.relpath(dirpath, PROJECT_ROOT)
        if rel.startswith("monitor"):
            continue
        if "config.json" in filenames:
            cfg_path = os.path.join(dirpath, "config.json")
            try:
                with open(cfg_path) as f:
                    cfg = json.load(f)
                actor_type = cfg.get("type")
                if actor_type not in SCRIPTS_BY_TYPE:
                    continue
                name = cfg.get("name")
                if not name:
                    continue
                found.append({
                    "name": name,
                    "type": actor_type,
                    "command_port": cfg.get("command_port"),
                    "config_path": cfg_path,
                    "is_active": cfg.get("is_active", True),
                    "partner_id": cfg.get("partner_id"),
                })
            except Exception as e:
                logger.warning("skipping config %s: %s", cfg_path, e)

    found.sort(key=lambda a: (STARTUP_ORDER.get(a["type"], 99), a["name"]))
    with _actors_lock:
        _actors = found
    return found


def get_actors():
    return discover_actors()


def is_running(name: str) -> bool:
    with _processes_lock:
        proc = _processes.get(name)
    if proc is None:
        return False
    return proc.poll() is None


def launch_actor(actor: dict):
    script = os.path.join(PROJECT_ROOT, SCRIPTS_BY_TYPE[actor["type"]])
    cmd = [sys.executable, script]
    if actor["type"] in NEEDS_CONFIG:
        cmd += ["--config", actor["config_path"]]
    proc = subprocess.Popen(cmd, cwd=PROJECT_ROOT)
    with _processes_lock:
        _processes[actor["name"]] = proc
    logger.info("launched %s (pid=%d)", actor["name"], proc.pid)


def wait_for_ready(actor: dict, timeout=10):
    port = actor.get("command_port")
    if not port:
        return
    actor_type = actor["type"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = requests.get(f"http://127.0.0.1:{port}/stats", timeout=1)
            if resp.status_code == 200:
                data = resp.json()
                conns = data.get("connections", {})
                if actor_type == "router" and not conns.get("downstream"):
                    time.sleep(0.3)
                    continue
                if actor_type == "upstream" and not conns.get("router"):
                    time.sleep(0.3)
                    continue
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


def _make_app(port):
    app = Flask(__name__, static_folder=None)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

    @app.route("/")
    def index():
        return send_from_directory(static_dir, "index.html")

    @app.route("/api/actors")
    def actors():
        result = []
        for a in get_actors():
            result.append({
                "name": a["name"],
                "type": a["type"],
                "command_port": a["command_port"],
                "running": is_running(a["name"]),
                "is_active": a["is_active"],
            })
        return jsonify(result)

    @app.route("/api/routers_by_partner")
    def routers_by_partner():
        result = {}
        for a in get_actors():
            if a["type"] != "router":
                continue
            pid = a.get("partner_id") or a["name"]
            result.setdefault(pid, []).append({
                "name": a["name"],
                "command_port": a["command_port"],
            })
        return jsonify(result)

    @app.route("/api/status")
    def status():
        result = {}
        for a in get_actors():
            name = a["name"]
            port = a.get("command_port")
            if not port or not is_running(name):
                result[name] = "red"
                continue
            try:
                resp = requests.get(f"http://127.0.0.1:{port}/stats", timeout=1)
                if resp.status_code != 200:
                    result[name] = "red"
                    continue
                data = resp.json()
                threshold = data.get("yellow_threshold_seconds")
                since = data.get("seconds_since_last_recv")
                if threshold is not None:
                    if since is None or since > threshold:
                        result[name] = "yellow"
                        continue
                result[name] = "green"
            except Exception:
                result[name] = "red"
        return jsonify(result)

    @app.route("/api/starting")
    def starting():
        with _starting_lock:
            return jsonify({"starting": _starting})

    @app.route("/api/csv_files")
    def csv_files():
        files = []
        csv_dir = os.path.join(PROJECT_ROOT, "test_csv_files")
        if os.path.isdir(csv_dir):
            for fn in os.listdir(csv_dir):
                if fn.endswith(".csv"):
                    files.append(f"test_csv_files/{fn}")
        for a in get_actors():
            if a["type"] == "upstream":
                cfg_dir = os.path.dirname(a["config_path"])
                input_dir = os.path.join(cfg_dir, "input")
                if os.path.isdir(input_dir):
                    for fn in os.listdir(input_dir):
                        if fn.endswith(".csv"):
                            rel = os.path.relpath(os.path.join(input_dir, fn), PROJECT_ROOT)
                            files.append(rel)
        return jsonify(files)

    def _proxy_get(name, path):
        actor = next((a for a in get_actors() if a["name"] == name), None)
        if not actor:
            return jsonify({"error": "not found"}), 404
        port = actor["command_port"]
        try:
            resp = requests.get(f"http://127.0.0.1:{port}/{path}", timeout=5)
            return resp.text, resp.status_code, {"Content-Type": resp.headers.get("Content-Type", "application/json")}
        except Exception as e:
            return jsonify({"error": str(e)}), 502

    def _proxy_post(name, path, **kwargs):
        actor = next((a for a in get_actors() if a["name"] == name), None)
        if not actor:
            return jsonify({"error": "not found"}), 404
        port = actor["command_port"]
        try:
            resp = requests.post(f"http://127.0.0.1:{port}/{path}", timeout=5, **kwargs)
            return resp.text, resp.status_code, {"Content-Type": resp.headers.get("Content-Type", "application/json")}
        except Exception as e:
            return jsonify({"error": str(e)}), 502

    @app.route("/api/actor/<name>/launch", methods=["POST"])
    def actor_launch(name):
        actor = next((a for a in get_actors() if a["name"] == name), None)
        if not actor:
            return jsonify({"error": "not found"}), 404
        if not is_running(name):
            launch_actor(actor)
        return jsonify({"status": "launched"})

    @app.route("/api/actor/<name>/stop", methods=["POST"])
    def actor_stop(name):
        return _proxy_post(name, "stop")

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
            return _proxy_post(name, "log_level", json=request.json)
        return _proxy_get(name, "log_level")

    @app.route("/api/actor/<name>/logs")
    def actor_logs(name):
        fmt = request.args.get("format", "json")
        return _proxy_get(name, f"logs?format={fmt}")

    @app.route("/api/actor/<name>/upload", methods=["POST"])
    def actor_upload(name):
        actor = next((a for a in get_actors() if a["name"] == name), None)
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
        actor = next((a for a in get_actors() if a["name"] == name), None)
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
        actors = list(reversed(get_actors()))
        for a in actors:
            if is_running(a["name"]):
                try:
                    requests.post(f"http://127.0.0.1:{a['command_port']}/stop", timeout=2)
                except Exception:
                    pass
        return jsonify({"status": "stopping"})

    @app.route("/stop", methods=["GET", "POST"])
    def stop_monitor():
        _terminate_all()
        os._exit(0)

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    def _shutdown(signum, frame):
        _terminate_all()
        os._exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    atexit.register(_terminate_all)

    app = _make_app(args.port)
    logger.info("monitor listening on port %d", args.port)
    app.run(host="0.0.0.0", port=args.port, use_reloader=False)


if __name__ == "__main__":
    main()

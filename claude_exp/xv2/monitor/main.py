#!/usr/bin/env python3
import argparse
import atexit
import json
import os
import subprocess
import sys
import threading
import time

import requests
from flask import Flask, jsonify, request as flask_request, send_from_directory

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MONITOR_DIR = os.path.dirname(os.path.abspath(__file__))

SCRIPTS_BY_TYPE = {
    "router":     "router/main.py",
    "upstream":   "simulators/upstream_host/main.py",
    "downstream": "simulators/downstream_host/main.py",
    "crypto":     "simulators/crypto_host/main.py",
}
TYPE_ORDER = {"crypto": 0, "downstream": 1, "router": 2, "upstream": 3}
NEEDS_CONFIG_ARG = {"router", "upstream"}


def discover_actors():
    actors = {}
    for root, _dirs, files in os.walk(BASE):
        if os.path.relpath(root, BASE).startswith("monitor"):
            continue
        if "config.json" not in files:
            continue
        try:
            with open(os.path.join(root, "config.json")) as f:
                cfg = json.load(f)
            name = cfg.get("name")
            atype = cfg.get("type")
            if not name or atype not in SCRIPTS_BY_TYPE:
                continue
            actors[name] = {
                "name":         name,
                "type":         atype,
                "command_port": cfg["command_port"],
                "script":       SCRIPTS_BY_TYPE[atype],
                "config_path":  os.path.join(root, "config.json"),
            }
        except Exception as e:
            print(f"Warning: could not read config in {root}: {e}")
    return actors


def _startup_order():
    return sorted(ACTORS, key=lambda n: (TYPE_ORDER.get(ACTORS[n]["type"], 99), n))


ACTORS = discover_actors()
_processes = {}
_proc_lock = threading.Lock()
_starting = False
_starting_lock = threading.Lock()

app = Flask(__name__, static_folder=os.path.join(MONITOR_DIR, "static"))


def _actor_url(name, path):
    a = ACTORS.get(name)
    return f"http://localhost:{a['command_port']}{path}" if a else None


def _wait_ready(name, timeout=10):
    url = _actor_url(name, "/stats")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            requests.get(url, timeout=0.5)
            return True
        except Exception:
            time.sleep(0.3)
    return False


# ── monitor stop ──────────────────────────────────────────────────────────────

@app.route("/stop", methods=["POST"])
def stop_monitor():
    _atexit_cleanup()
    threading.Timer(0.3, os._exit, args=[0]).start()
    return jsonify({"status": "stopping"})


# ── static ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ── actor discovery ───────────────────────────────────────────────────────────

@app.route("/api/actors")
def api_actors():
    result = []
    for name in _startup_order():
        a = ACTORS[name]
        result.append({"name": a["name"], "type": a["type"], "command_port": a["command_port"]})
    return jsonify(result)


# ── batch status (single round-trip) ─────────────────────────────────────────

@app.route("/api/status")
def api_status():
    result = {}
    lock = threading.Lock()

    def check(name):
        try:
            requests.get(_actor_url(name, "/stats"), timeout=0.5)
            with lock:
                result[name] = True
        except Exception:
            with lock:
                result[name] = False

    threads = [threading.Thread(target=check, args=(n,)) for n in ACTORS]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=1.5)
    return jsonify(result)


@app.route("/api/starting")
def api_is_starting():
    return jsonify({"starting": _starting})


# ── project csv discovery ────────────────────────────────────────────────────

@app.route("/api/csv_files")
def api_csv_files():
    import glob
    found = []
    for path in sorted(glob.glob(os.path.join(BASE, "test_csv_files", "*.csv"))):
        found.append(os.path.relpath(path, BASE))
    for name, a in ACTORS.items():
        if a["type"] == "upstream":
            cfg_dir = os.path.dirname(a["config_path"])
            for path in sorted(glob.glob(os.path.join(cfg_dir, "input", "*.csv"))):
                found.append(os.path.relpath(path, BASE))
    return jsonify(found)


@app.route("/api/actor/<name>/upload_path", methods=["POST"])
def api_upload_path(name):
    url = _actor_url(name, "/upload")
    if not url:
        return jsonify({"error": "unknown actor"}), 404
    rel = (flask_request.json or {}).get("path", "")
    full = os.path.normpath(os.path.join(BASE, rel))
    if not full.startswith(BASE) or not os.path.isfile(full):
        return jsonify({"error": f"file not found: {rel}"}), 404
    try:
        with open(full, "rb") as f:
            r = requests.post(url, files={"file": (os.path.basename(full), f, "text/csv")}, timeout=10)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 503


# ── per-actor proxy ───────────────────────────────────────────────────────────

@app.route("/api/actor/<name>/launch", methods=["POST"])
def api_launch(name):
    a = ACTORS.get(name)
    if not a:
        return jsonify({"error": "unknown actor"}), 404
    with _proc_lock:
        existing = _processes.get(name)
        if existing and existing.poll() is None:
            return jsonify({"status": "already running"}), 200
        cmd = [sys.executable, os.path.join(BASE, a["script"])]
        if a["type"] in NEEDS_CONFIG_ARG:
            cmd += ["--config", a["config_path"]]
        proc = subprocess.Popen(cmd, cwd=BASE)
        _processes[name] = proc
    return jsonify({"status": "started"})


@app.route("/api/actor/<name>/stats")
def api_stats(name):
    url = _actor_url(name, "/stats")
    if not url:
        return jsonify({"error": "unknown actor"}), 404
    try:
        r = requests.get(url, timeout=2)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 503


@app.route("/api/actor/<name>/stop", methods=["POST"])
def api_stop(name):
    url = _actor_url(name, "/stop")
    if not url:
        return jsonify({"error": "unknown actor"}), 404
    try:
        r = requests.post(url, timeout=2)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 503


@app.route("/api/actor/<name>/upload", methods=["POST"])
def api_upload(name):
    url = _actor_url(name, "/upload")
    if not url:
        return jsonify({"error": "unknown actor"}), 404
    f = flask_request.files.get("file")
    if not f:
        return jsonify({"error": "no file"}), 400
    try:
        r = requests.post(url, files={"file": (f.filename, f.stream, f.content_type)}, timeout=10)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 503


@app.route("/api/actor/<name>/start")
def api_start(name):
    url = _actor_url(name, "/start")
    if not url:
        return jsonify({"error": "unknown actor"}), 404
    try:
        r = requests.get(url, timeout=10)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 503


@app.route("/api/actor/<name>/results")
def api_results(name):
    url = _actor_url(name, "/results")
    if not url:
        return jsonify({"error": "unknown actor"}), 404
    try:
        r = requests.get(url, timeout=5)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 503


@app.route("/api/actor/<name>/log_level", methods=["GET", "POST"])
def api_log_level(name):
    url = _actor_url(name, "/log_level")
    if not url:
        return jsonify({"error": "unknown actor"}), 404
    try:
        if flask_request.method == "POST":
            r = requests.post(url, json=flask_request.json, timeout=2)
        else:
            r = requests.get(url, timeout=2)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 503


@app.route("/api/actor/<name>/logs")
def api_logs(name):
    url = _actor_url(name, "/logs")
    if not url:
        return jsonify({"error": "unknown actor"}), 404
    fmt = flask_request.args.get("format", "")
    try:
        r = requests.get(url, params={"format": fmt} if fmt else {}, timeout=5)
        if fmt == "text":
            from flask import Response
            return Response(r.text, mimetype="text/plain")
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 503


# ── global start / stop ───────────────────────────────────────────────────────

@app.route("/api/start_all", methods=["POST"])
def api_start_all():
    global _starting
    with _starting_lock:
        if _starting:
            return jsonify({"status": "already starting"}), 409
        _starting = True

    def _do_start():
        global _starting
        try:
            for name in _startup_order():
                a = ACTORS[name]
                with _proc_lock:
                    existing = _processes.get(name)
                    if existing and existing.poll() is None:
                        continue
                    cmd = [sys.executable, os.path.join(BASE, a["script"])]
                    if a["type"] in NEEDS_CONFIG_ARG:
                        cmd += ["--config", a["config_path"]]
                    proc = subprocess.Popen(cmd, cwd=BASE)
                    _processes[name] = proc
                _wait_ready(name, timeout=10)
        finally:
            _starting = False

    threading.Thread(target=_do_start, daemon=True).start()
    return jsonify({"status": "starting"})


def _terminate_proc(proc, timeout=5):
    if proc and proc.poll() is None:
        proc.terminate()
    if proc:
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


@app.route("/api/stop_all", methods=["POST"])
def api_stop_all():
    results = {}
    for name in reversed(_startup_order()):
        try:
            requests.post(_actor_url(name, "/stop"), timeout=2)
            results[name] = "stopped"
        except Exception:
            results[name] = "not reachable"
        with _proc_lock:
            proc = _processes.pop(name, None)
        _terminate_proc(proc)
    return jsonify(results)


def _atexit_cleanup():
    with _proc_lock:
        procs = list(_processes.values())
        _processes.clear()
    for proc in procs:
        _terminate_proc(proc, timeout=3)


atexit.register(_atexit_cleanup)


# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    import logging as _logging
    _logging.getLogger("werkzeug").setLevel(_logging.ERROR)
    print(f"UI → http://localhost:{args.port}")
    app.run(host="0.0.0.0", port=args.port, debug=False)

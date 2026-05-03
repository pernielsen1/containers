#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import threading
import time

import requests
from flask import Flask, jsonify, request as flask_request, send_from_directory

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.dirname(os.path.abspath(__file__))

ACTOR_SCRIPTS = {
    "router":          "router/main.py",
    "crypto_host":     "simulators/crypto_host/main.py",
    "downstream_host": "simulators/downstream_host/main.py",
    "upstream_host":   "simulators/upstream_host/main.py",
}
STARTUP_ORDER = ["crypto_host", "downstream_host", "router", "upstream_host"]


def discover_actors():
    actors = {}
    for root, _dirs, files in os.walk(BASE):
        if os.path.relpath(root, BASE).startswith("ui"):
            continue
        if "config.json" in files:
            name = os.path.basename(root)
            if name not in ACTOR_SCRIPTS:
                continue
            try:
                with open(os.path.join(root, "config.json")) as f:
                    cfg = json.load(f)
                actors[name] = {
                    "name": name,
                    "command_port": cfg["command_port"],
                    "script": ACTOR_SCRIPTS[name],
                    "type": name,
                }
            except Exception as e:
                print(f"Warning: could not read config for {name}: {e}")
    return actors


ACTORS = discover_actors()
_processes = {}
_proc_lock = threading.Lock()
_starting = False
_starting_lock = threading.Lock()

app = Flask(__name__, static_folder=os.path.join(UI_DIR, "static"))


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


# ── static ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ── actor discovery ───────────────────────────────────────────────────────────

@app.route("/api/actors")
def api_actors():
    result = []
    for name in STARTUP_ORDER:
        if name in ACTORS:
            a = {k: v for k, v in ACTORS[name].items() if k != "script"}
            result.append(a)
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
    patterns = [
        os.path.join(BASE, "test_csv_files", "*.csv"),
        os.path.join(BASE, "simulators", "upstream_host", "input", "*.csv"),
    ]
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
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
            for name in STARTUP_ORDER:
                if name not in ACTORS:
                    continue
                with _proc_lock:
                    existing = _processes.get(name)
                    if existing and existing.poll() is None:
                        continue
                    proc = subprocess.Popen(
                        [sys.executable, os.path.join(BASE, ACTORS[name]["script"])],
                        cwd=BASE,
                    )
                    _processes[name] = proc
                _wait_ready(name, timeout=10)
        finally:
            _starting = False

    threading.Thread(target=_do_start, daemon=True).start()
    return jsonify({"status": "starting"})


@app.route("/api/stop_all", methods=["POST"])
def api_stop_all():
    results = {}
    for name in reversed(STARTUP_ORDER):
        if name not in ACTORS:
            continue
        try:
            requests.post(_actor_url(name, "/stop"), timeout=2)
            results[name] = "stopped"
        except Exception:
            results[name] = "not reachable"
        with _proc_lock:
            proc = _processes.pop(name, None)
        if proc and proc.poll() is None:
            proc.terminate()
    return jsonify(results)


# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    print(f"UI → http://localhost:{args.port}")
    app.run(host="0.0.0.0", port=args.port, debug=False)

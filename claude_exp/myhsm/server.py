#!/usr/bin/env python3
"""Fortanix DSM simulator — supports plugin invocation."""

import importlib.util
import os
import secrets
import sys
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, request

app = Flask(__name__)

USERS = {"admin": "admin123"}
TOKENS: dict[str, str] = {}  # token -> username
PLUGINS_DIR = Path(__file__).parent / "plugins"


def load_plugin(name: str):
    path = PLUGINS_DIR / f"{name}.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "missing or invalid Authorization header"}), 401
        token = auth.removeprefix("Bearer ")
        if token not in TOKENS:
            return jsonify({"error": "invalid token"}), 401
        return f(*args, **kwargs)
    return wrapper


@app.post("/sys/v1/session/auth")
def session_auth():
    auth = request.authorization
    if not auth or USERS.get(auth.username) != auth.password:
        return jsonify({"error": "invalid credentials"}), 401
    token = secrets.token_hex(32)
    TOKENS[token] = auth.username
    return jsonify({"access_token": token, "token_type": "Bearer"})


@app.post("/crypto/v1/plugins/<plugin_name>")
@require_auth
def invoke_plugin(plugin_name: str):
    mod = load_plugin(plugin_name)
    if mod is None:
        return jsonify({"error": f"plugin '{plugin_name}' not found"}), 404

    body = request.get_json(silent=True) or {}
    input_data = body.get("input", "")

    try:
        result = mod.run(input_data)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"result": result})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    app.run(port=port, debug=True)

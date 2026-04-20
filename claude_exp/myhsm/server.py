#!/usr/bin/env python3
"""Fortanix DSM simulator — supports plugin invocation and crypto key operations."""

import importlib.util
import secrets
import sys
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, request

import keystore

app = Flask(__name__)

USERS = {"admin": "admin123"}
TOKENS: dict[str, str] = {}  # token -> username
PLUGINS_DIR = Path(__file__).parent / "plugins"
KEYSTORE_PATH = Path(__file__).parent / "keystore.json"


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


@app.post("/crypto/v1/keys/derive")
@require_auth
def derive_key():
    body = request.get_json(silent=True) or {}
    keyname = body.get("keyname")
    diversify = body.get("diversify")

    if not keyname:
        return jsonify({"error": "keyname is required"}), 400
    if not diversify:
        return jsonify({"error": "diversify is required"}), 400

    base_key = keystore.get(keyname)
    if base_key is None:
        return jsonify({"error": f"key '{keyname}' not found in keystore"}), 404

    try:
        div_bytes = bytes.fromhex(diversify)
    except ValueError:
        return jsonify({"error": "diversify must be a hex string"}), 400

    # XOR key bytes with diversify bytes (cycle diversify if shorter)
    derived = bytes(b ^ div_bytes[i % len(div_bytes)] for i, b in enumerate(base_key))
    token_id = diversify + keyname
    keystore.put(token_id, derived)

    return jsonify({"token_id": token_id})


@app.post("/crypto/v1/plugins/<plugin_name>")
@require_auth
def invoke_plugin(plugin_name: str):
    mod = load_plugin(plugin_name)
    if mod is None:
        return jsonify({"error": f"plugin '{plugin_name}' not found"}), 404

    body = request.get_json(silent=True) or {}

    try:
        result = mod.run(body)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify(result)


if __name__ == "__main__":
    keystore.load(KEYSTORE_PATH)
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    app.run(port=port, debug=True)

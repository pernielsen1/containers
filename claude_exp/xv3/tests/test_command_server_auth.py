import threading
import time

import requests

from shared.command_server import CommandServer
from shared.stats import Stats


def make_server(auth_token, port=0):
    stats = Stats()
    stop_event = threading.Event()
    cmd = CommandServer(port=port, stats=stats, stop_event=stop_event, auth_token=auth_token)
    return cmd


def test_protected_routes_reject_missing_or_wrong_token():
    cmd = make_server(auth_token="s3cr3t")
    client = cmd.app.test_client()

    for path in ("/stop", "/log_level"):
        resp = client.post(path)
        assert resp.status_code == 403, f"{path} should reject a missing token"

        resp = client.post(path, headers={"X-Router-Auth": "wrong"})
        assert resp.status_code == 403, f"{path} should reject the wrong token"

        resp = client.post(path, headers={"X-Router-Auth": "s3cr3t"})
        assert resp.status_code == 200, f"{path} should accept the correct token"


def test_unprotected_routes_unaffected_by_auth_token():
    cmd = make_server(auth_token="s3cr3t")
    client = cmd.app.test_client()

    assert client.get("/stats").status_code == 200
    assert client.get("/logs").status_code == 200
    # GET /log_level is unprotected even though POST is gated
    assert client.get("/log_level").status_code == 200


def test_custom_registered_route_respects_protected_flag():
    cmd = make_server(auth_token="s3cr3t")

    @cmd.register("/dispatcher/purge", methods=["POST"], protected=True)
    def purge():
        from flask import jsonify

        return jsonify({"purged": True})

    client = cmd.app.test_client()
    assert client.post("/dispatcher/purge").status_code == 403
    assert client.post("/dispatcher/purge", headers={"X-Router-Auth": "wrong"}).status_code == 403
    assert client.post("/dispatcher/purge", headers={"X-Router-Auth": "s3cr3t"}).status_code == 200


def test_no_auth_token_means_protected_routes_are_open():
    # command_auth_token defaults to None on every actor config (see Known limitations) —
    # protected routes are then reachable without a header at all.
    cmd = make_server(auth_token=None)
    client = cmd.app.test_client()
    assert client.post("/stop").status_code == 200


def test_default_bind_host_is_loopback():
    stats = Stats()
    stop_event = threading.Event()
    cmd = CommandServer(port=0, stats=stats, stop_event=stop_event)
    assert cmd.bind_host == "127.0.0.1"


def test_loopback_bind_actually_accepts_local_connections():
    stats = Stats()
    stop_event = threading.Event()
    port = 28699
    cmd = CommandServer(port=port, stats=stats, stop_event=stop_event)
    cmd.start()
    time.sleep(0.4)
    try:
        resp = requests.get(f"http://127.0.0.1:{port}/stats", timeout=2)
        assert resp.status_code == 200
    finally:
        stop_event.set()

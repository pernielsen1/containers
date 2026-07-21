import threading
import time

import requests

from shared.command_server import CommandServer
from shared.stats import Stats


def _start_server(port, auth_token=None):
    stats = Stats()
    stop_event = threading.Event()
    cmd = CommandServer(port, stats, stop_event, auth_token=auth_token)
    cmd.start()
    time.sleep(0.3)
    return cmd, stats, stop_event


def test_protected_route_rejects_missing_token():
    _, _, stop_event = _start_server(18801, auth_token="secret")
    resp = requests.post("http://127.0.0.1:18801/stop")
    assert resp.status_code == 401
    assert not stop_event.is_set()


def test_protected_route_rejects_wrong_token():
    _, _, stop_event = _start_server(18802, auth_token="secret")
    resp = requests.post("http://127.0.0.1:18802/stop", headers={"X-Router-Auth": "wrong"})
    assert resp.status_code == 401
    assert not stop_event.is_set()


def test_protected_route_accepts_correct_token():
    _, _, stop_event = _start_server(18803, auth_token="secret")
    resp = requests.post("http://127.0.0.1:18803/stop", headers={"X-Router-Auth": "secret"})
    assert resp.status_code == 200
    assert stop_event.is_set()


def test_unprotected_route_unaffected_by_auth_token():
    _start_server(18804, auth_token="secret")
    resp = requests.get("http://127.0.0.1:18804/stats")
    assert resp.status_code == 200


def test_default_bind_is_loopback():
    cmd, _, _ = _start_server(18805)
    assert cmd.bind_host == "127.0.0.1"

import sys
import os
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from shared.command_server import CommandServer
from shared.stats import Stats


def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def make_auth_server(token="secret123"):
    port = free_port()
    stop_event = threading.Event()
    stats = Stats()
    cmd = CommandServer(
        port=port, stats=stats, stop_event=stop_event,
        bind_host="127.0.0.1", auth_token=token,
    )
    cmd.start()
    time.sleep(0.3)
    return port, stop_event, token


def test_stats_no_auth_required():
    port, stop_event, token = make_auth_server()
    r = requests.get(f"http://127.0.0.1:{port}/stats")
    assert r.status_code == 200


def test_stop_requires_auth():
    port, stop_event, token = make_auth_server()
    r = requests.post(f"http://127.0.0.1:{port}/stop")
    assert r.status_code == 401
    assert not stop_event.is_set()


def test_stop_wrong_token():
    port, stop_event, token = make_auth_server()
    r = requests.post(f"http://127.0.0.1:{port}/stop",
                      headers={"X-Router-Auth": "wrongtoken"})
    assert r.status_code == 401


def test_stop_correct_token():
    port, stop_event, token = make_auth_server()
    r = requests.post(f"http://127.0.0.1:{port}/stop",
                      headers={"X-Router-Auth": token})
    assert r.status_code == 200
    assert stop_event.is_set()


def test_log_level_post_requires_auth():
    port, stop_event, token = make_auth_server()
    r = requests.post(f"http://127.0.0.1:{port}/log_level", json={"level": "DEBUG"})
    assert r.status_code == 401


def test_log_level_get_no_auth():
    port, stop_event, token = make_auth_server()
    r = requests.get(f"http://127.0.0.1:{port}/log_level")
    assert r.status_code == 200


def test_no_auth_token_bypasses_check():
    port = free_port()
    stop_event = threading.Event()
    stats = Stats()
    cmd = CommandServer(port=port, stats=stats, stop_event=stop_event, auth_token=None)
    cmd.start()
    time.sleep(0.3)
    r = requests.post(f"http://127.0.0.1:{port}/stop")
    assert r.status_code == 200
    assert stop_event.is_set()


def test_default_bind_is_loopback():
    port = free_port()
    stop_event = threading.Event()
    stats = Stats()
    cmd = CommandServer(port=port, stats=stats, stop_event=stop_event)
    cmd.start()
    time.sleep(0.3)
    r = requests.get(f"http://127.0.0.1:{port}/stats")
    assert r.status_code == 200

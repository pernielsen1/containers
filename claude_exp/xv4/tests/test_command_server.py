import sys
import os
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
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


def make_server(port=None):
    if port is None:
        port = free_port()
    stop_event = threading.Event()
    stats = Stats(yellow_threshold_seconds=30)
    stats.record_sent()
    cmd = CommandServer(port=port, stats=stats, stop_event=stop_event)
    cmd.start()
    time.sleep(0.3)
    return cmd, stop_event, stats, port


def test_stats_endpoint():
    cmd, stop_event, stats, port = make_server()
    r = requests.get(f"http://127.0.0.1:{port}/stats")
    assert r.status_code == 200
    data = r.json()
    assert "sent_total" in data
    assert data["sent_total"] == 1
    assert data["yellow_threshold_seconds"] == 30


def test_stop_endpoint():
    cmd, stop_event, stats, port = make_server()
    assert not stop_event.is_set()
    r = requests.post(f"http://127.0.0.1:{port}/stop")
    assert r.status_code == 200
    assert stop_event.is_set()


def test_log_level_get():
    cmd, stop_event, stats, port = make_server()
    r = requests.get(f"http://127.0.0.1:{port}/log_level")
    assert r.status_code == 200
    assert "level" in r.json()


def test_log_level_post():
    cmd, stop_event, stats, port = make_server()
    r = requests.post(f"http://127.0.0.1:{port}/log_level", json={"level": "DEBUG"})
    assert r.status_code == 200
    assert r.json()["level"] == "DEBUG"


def test_logs_endpoint():
    cmd, stop_event, stats, port = make_server()
    r = requests.get(f"http://127.0.0.1:{port}/logs")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_logs_text_format():
    cmd, stop_event, stats, port = make_server()
    r = requests.get(f"http://127.0.0.1:{port}/logs?format=text")
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("text/plain")

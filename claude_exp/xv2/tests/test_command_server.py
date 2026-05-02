import threading
import time
import requests
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared.stats import Stats
from shared.command_server import CommandServer

PORT = 19800


def make_server(port=PORT):
    stop_event = threading.Event()
    stats = Stats()
    stats.record_sent()
    stats.record_recv()
    srv = CommandServer(port, stats, stop_event)
    srv.start()
    time.sleep(0.3)
    return srv, stats, stop_event


def test_stats_endpoint():
    srv, stats, stop_event = make_server(PORT)
    try:
        r = requests.get(f"http://localhost:{PORT}/stats", timeout=3)
        assert r.status_code == 200
        body = r.json()
        assert "sent_30s" in body
        assert body["sent_30s"] == 1
        assert body["recv_30s"] == 1
    finally:
        stop_event.set()


def test_stop_sets_event():
    srv, stats, stop_event = make_server(PORT + 1)
    try:
        assert not stop_event.is_set()
        r = requests.post(f"http://localhost:{PORT + 1}/stop", timeout=3)
        assert r.status_code == 200
        time.sleep(0.1)
        assert stop_event.is_set()
    finally:
        stop_event.set()


def test_custom_route():
    stop_event = threading.Event()
    stats = Stats()
    srv = CommandServer(PORT + 2, stats, stop_event)

    @srv.register("/ping")
    def ping():
        return {"pong": True}

    srv.start()
    time.sleep(0.3)
    try:
        r = requests.get(f"http://localhost:{PORT + 2}/ping", timeout=3)
        assert r.status_code == 200
        assert r.json() == {"pong": True}
    finally:
        stop_event.set()


def test_unknown_route_returns_404():
    srv, _, stop_event = make_server(PORT + 3)
    try:
        r = requests.get(f"http://localhost:{PORT + 3}/nope", timeout=3)
        assert r.status_code == 404
    finally:
        stop_event.set()

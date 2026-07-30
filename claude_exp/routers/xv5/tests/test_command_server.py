import logging
import threading
import time

import requests

from shared.command_server import CommandServer
from shared.stats import Stats


def _start_server(port, **kwargs):
    stats = Stats()
    stop_event = threading.Event()
    cmd = CommandServer(port, stats, stop_event, **kwargs)
    cmd.start()
    time.sleep(0.3)
    return cmd, stats, stop_event


def test_stats_route():
    _, stats, _ = _start_server(18701)
    stats.record_sent()
    resp = requests.get("http://127.0.0.1:18701/stats")
    assert resp.status_code == 200
    assert resp.json()["sent_total"] == 1


def test_stop_route():
    _, _, stop_event = _start_server(18702)
    resp = requests.post("http://127.0.0.1:18702/stop")
    assert resp.status_code == 200
    assert stop_event.is_set()


def test_log_level_route():
    _start_server(18703)
    resp = requests.post("http://127.0.0.1:18703/log_level", json={"level": "DEBUG"})
    assert resp.status_code == 200
    assert resp.json()["level"] == "DEBUG"

    resp = requests.get("http://127.0.0.1:18703/log_level")
    assert resp.json()["level"] == "DEBUG"


def test_logs_route():
    _start_server(18704)
    logging.getLogger("test_command_server_logger").warning("hello from test")

    resp = requests.get("http://127.0.0.1:18704/logs")
    assert resp.status_code == 200
    assert any("hello from test" in line for line in resp.json())

    resp_text = requests.get("http://127.0.0.1:18704/logs?format=text")
    assert "hello from test" in resp_text.text

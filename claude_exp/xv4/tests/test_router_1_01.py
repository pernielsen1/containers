import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import requests

from router.config import RouterConfig
from router import main as router_main
from shared.iso_utils import load_spec

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def wait_for_http(port, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"http://127.0.0.1:{port}/stats", timeout=1)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def wait_for_connection(port, key, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"http://127.0.0.1:{port}/stats", timeout=1)
            if r.status_code == 200:
                if r.json().get("connections", {}).get(key):
                    return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


@pytest.fixture(scope="module")
def router_1_01_stack(shared_infra):
    import logging
    logging.basicConfig(level=logging.WARNING)

    stops = []

    # Router 1.01
    r_stop = threading.Event()
    stops.append(r_stop)
    r_cfg = RouterConfig.from_file(os.path.join(PROJECT_ROOT, "router/router_1.01/config.json"))
    threading.Thread(
        target=router_main.run,
        kwargs={"cfg": r_cfg, "stop_event": r_stop},
        daemon=True,
    ).start()
    assert wait_for_http(r_cfg.command_port)
    assert wait_for_connection(r_cfg.command_port, "downstream")

    yield {"router_port": r_cfg.command_port}

    for s in stops:
        s.set()


def test_router_1_01_stats(router_1_01_stack):
    port = router_1_01_stack["router_port"]
    r = requests.get(f"http://127.0.0.1:{port}/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["connections"]["downstream"] is True


def test_router_1_01_downstream_connected(router_1_01_stack):
    port = router_1_01_stack["router_port"]
    r = requests.get(f"http://127.0.0.1:{port}/stats")
    assert r.json()["connections"].get("downstream") is True

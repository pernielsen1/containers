import csv
import io
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
from simulators.downstream_host import main as ds_main
from simulators.crypto_host import main as crypto_main
from simulators.upstream_host import main as upstream_main
from shared.iso_utils import load_spec
from shared.stats import Stats

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = load_spec(os.path.join(PROJECT_ROOT, "test_spec.json"))


def wait_for_http(port, path="stats", timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"http://127.0.0.1:{port}/{path}", timeout=1)
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
                data = r.json()
                if data.get("connections", {}).get(key):
                    return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


@pytest.fixture(scope="module")
def full_stack(shared_infra):
    pans = shared_infra["pans"]
    stops = []

    # Router
    router_stop = threading.Event()
    stops.append(router_stop)
    router_cfg = RouterConfig.from_file(os.path.join(PROJECT_ROOT, "router/router_1/config.json"))
    router_thread = threading.Thread(
        target=router_main.run,
        kwargs={"cfg": router_cfg, "stop_event": router_stop},
        daemon=True,
    )
    router_thread.start()
    assert wait_for_http(router_cfg.command_port), "router didn't start"
    assert wait_for_connection(router_cfg.command_port, "downstream"), "router didn't connect to downstream"

    # Upstream host
    up_stop = threading.Event()
    stops.append(up_stop)
    up_cfg_path = os.path.join(PROJECT_ROOT, "simulators/upstream_1/config.json")
    with open(up_cfg_path) as f:
        up_cfg = json.load(f)
    up_spec = load_spec(os.path.join(PROJECT_ROOT, "test_spec.json"))
    up_host = upstream_main.UpstreamHost(up_cfg, up_spec, cfg_dir=os.path.dirname(up_cfg_path))
    up_host.stop_event = up_stop
    upstream_main.make_app(up_host)
    up_host.start_connect_loop()
    assert wait_for_http(up_cfg["command_port"]), "upstream didn't start"
    assert wait_for_connection(up_cfg["command_port"], "router"), "upstream didn't connect to router"

    yield {
        "router_port": router_cfg.command_port,
        "up_port": up_cfg["command_port"],
        "up_name": up_cfg["name"],
        "up_host": up_host,
    }

    for s in stops:
        s.set()


def test_full_stack_basic(full_stack):
    # Write known CSV content
    csv_content = "2;3;4;11;expected_39\n4111111111111111;000000;000000000100;000001;00\n"
    up_host = full_stack["up_host"]
    up_host.upload_csv(csv_content.encode("utf-8-sig"), "test_cases.csv")

    # Start
    n = up_host.start_send()
    assert n == 1

    # Poll results
    deadline = time.monotonic() + 15
    results = []
    while time.monotonic() < deadline:
        results = up_host.get_results()
        if results:
            break
        time.sleep(0.5)

    assert len(results) >= 1
    row = results[0]
    assert row.get("resp_39") == "00", f"Expected rc=00, got {row.get('resp_39')}"


def test_full_stack_unknown_pan(full_stack):
    csv_content = "2;3;4;11;expected_39\n9999999999999999;000000;000000000100;000001;05\n"
    up_host = full_stack["up_host"]
    # Clear previous results
    with up_host._results_lock:
        up_host._results.clear()
    up_host.upload_csv(csv_content.encode("utf-8-sig"), "test_cases.csv")

    n = up_host.start_send()
    assert n == 1

    deadline = time.monotonic() + 15
    results = []
    while time.monotonic() < deadline:
        results = up_host.get_results()
        if results:
            break
        time.sleep(0.5)

    assert len(results) >= 1
    row = results[0]
    assert row.get("resp_39") != "00", f"Expected decline, got {row.get('resp_39')}"

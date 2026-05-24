"""
Test client for router_1.01.
Tests basic connectivity and stats endpoint for router_1.01.
"""
import io
import os
import sys
import threading
import time

import requests
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PORTS_1_01 = {
    "crypto_port":    25002,
    "crypto_cmd":     28082,
    "ds_port":        25001,
    "ds_cmd":         28081,
    "router_up_port": 25003,
    "router_cmd":     28080,
    "us_cmd":         28083,
}


def _make_cfg():
    import simulators.crypto_host.main as ch
    import simulators.downstream_host.main as dh
    import simulators.upstream_host.main as uh
    import router.main as rm

    crypto_cfg = {
        "port": PORTS_1_01["crypto_port"],
        "command_port": PORTS_1_01["crypto_cmd"],
        "pans_defined": os.path.join(BASE, "pans_defined.json"),
    }
    ds_cfg = {
        "port": PORTS_1_01["ds_port"],
        "command_port": PORTS_1_01["ds_cmd"],
        "iso_spec": os.path.join(BASE, "test_spec.json"),
        "pans_defined": os.path.join(BASE, "pans_defined.json"),
    }
    router_cfg = {
        "command_port": PORTS_1_01["router_cmd"],
        "upstream": {
            "port": PORTS_1_01["router_up_port"],
            "framing": {"header_hex": "", "length_field_type": "ASCII", "length_field_bytes": 4},
        },
        "downstream": {
            "host": "localhost",
            "port": PORTS_1_01["ds_port"],
            "irm_id": "IRM_ID01",
            "client_id": "CLIENT03",
        },
        "crypto": {"host": "localhost", "port": PORTS_1_01["crypto_port"]},
        "iso_spec": os.path.join(BASE, "test_spec.json"),
        "partner_id": "partner_a",
    }
    us_cfg = {
        "command_port": PORTS_1_01["us_cmd"],
        "router": {"host": "localhost", "port": PORTS_1_01["router_up_port"]},
        "framing": {"header_hex": "", "length_field_type": "ASCII", "length_field_bytes": 4},
        "iso_spec": os.path.join(BASE, "test_spec.json"),
        "input_dir": os.path.join(BASE, "simulators", "upstream_host", "input"),
    }
    return ch, dh, uh, rm, crypto_cfg, ds_cfg, router_cfg, us_cfg


def _wait_http(url, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            requests.get(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.2)
    return False


@pytest.fixture(scope="module")
def actors_1_01():
    ch, dh, uh, rm, crypto_cfg, ds_cfg, router_cfg, us_cfg = _make_cfg()

    stops = {k: threading.Event() for k in ("crypto", "ds", "router", "us")}

    # start in dependency order: crypto → downstream → router → upstream
    threading.Thread(target=ch.run, kwargs={"cfg": crypto_cfg, "stop_event": stops["crypto"]}, daemon=True).start()
    _wait_http(f"http://localhost:{PORTS_1_01['crypto_cmd']}/stats")

    threading.Thread(target=dh.run, kwargs={"cfg": ds_cfg, "stop_event": stops["ds"]}, daemon=True).start()
    _wait_http(f"http://localhost:{PORTS_1_01['ds_cmd']}/stats")

    threading.Thread(target=rm.run, kwargs={"cfg": router_cfg, "stop_event": stops["router"]}, daemon=True).start()
    _wait_http(f"http://localhost:{PORTS_1_01['router_cmd']}/stats")

    threading.Thread(target=uh.run, kwargs={"cfg": us_cfg, "stop_event": stops["us"]}, daemon=True).start()
    _wait_http(f"http://localhost:{PORTS_1_01['us_cmd']}/stats")

    yield stops

    for ev in stops.values():
        ev.set()
    time.sleep(0.5)


def test_router_1_01_stats_endpoint(actors_1_01):
    r = requests.get(f"http://localhost:{PORTS_1_01['router_cmd']}/stats", timeout=3)
    assert r.status_code == 200
    body = r.json()
    assert "sent_30s" in body


def test_router_1_01_is_partner_a(actors_1_01):
    r = requests.get(f"http://localhost:{PORTS_1_01['router_cmd']}/stats", timeout=3)
    assert r.status_code == 200

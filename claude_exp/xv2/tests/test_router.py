"""
Integration test: starts all four actors in threads, uploads a CSV via
upstream_host, calls /start, waits for responses, verifies field 39.
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

PORTS = {
    "crypto_port":    15002,
    "crypto_cmd":     18082,
    "ds_to_port":     15001,
    "ds_from_port":   15003,
    "ds_cmd":         18081,
    "router_up_port": 15000,
    "router_cmd":     18080,
    "us_cmd":         18083,
}

TEST_CSV = (
    "2;3;4;11;expected_39\n"
    "4111111111111111;000000;000000000100;000001;00\n"   # known PAN, crypto_result=True → approve
    "4222222222222222;000000;000000000100;000002;01\n"   # known PAN, crypto_result=False → decline
    "9999999999999999;000000;000000000100;000003;01\n"   # unknown PAN → decline
)


def _make_cfg():
    import simulators.crypto_host.main as ch
    import simulators.downstream_host.main as dh
    import simulators.upstream_host.main as uh
    import router.main as rm

    crypto_cfg = {
        "port": PORTS["crypto_port"],
        "command_port": PORTS["crypto_cmd"],
        "pans_defined": os.path.join(BASE, "pans_defined.json"),
    }
    ds_cfg = {
        "to_downstream_port": PORTS["ds_to_port"],
        "from_downstream_port": PORTS["ds_from_port"],
        "command_port": PORTS["ds_cmd"],
        "iso_spec": os.path.join(BASE, "test_spec.json"),
        "pans_defined": os.path.join(BASE, "pans_defined.json"),
    }
    router_cfg = {
        "command_port": PORTS["router_cmd"],
        "upstream": {
            "port": PORTS["router_up_port"],
            "framing": {"header_hex": "", "length_field_type": "ASCII", "length_field_bytes": 4},
        },
        "downstream": {
            "host": "localhost",
            "to_downstream_port": PORTS["ds_to_port"],
            "from_downstream_port": PORTS["ds_from_port"],
            "irm_id": "IRM_ID01",
            "client_id": "CLIENT01",
        },
        "crypto": {"host": "localhost", "port": PORTS["crypto_port"]},
        "iso_spec": os.path.join(BASE, "test_spec.json"),
    }
    us_cfg = {
        "command_port": PORTS["us_cmd"],
        "router": {"host": "localhost", "port": PORTS["router_up_port"]},
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
def actors():
    ch, dh, uh, rm, crypto_cfg, ds_cfg, router_cfg, us_cfg = _make_cfg()

    stops = {k: threading.Event() for k in ("crypto", "ds", "router", "us")}

    # start in dependency order: crypto → downstream → router → upstream
    threading.Thread(target=ch.run, kwargs={"cfg": crypto_cfg, "stop_event": stops["crypto"]}, daemon=True).start()
    _wait_http(f"http://localhost:{PORTS['crypto_cmd']}/stats")

    threading.Thread(target=dh.run, kwargs={"cfg": ds_cfg, "stop_event": stops["ds"]}, daemon=True).start()
    _wait_http(f"http://localhost:{PORTS['ds_cmd']}/stats")

    threading.Thread(target=rm.run, kwargs={"cfg": router_cfg, "stop_event": stops["router"]}, daemon=True).start()
    _wait_http(f"http://localhost:{PORTS['router_cmd']}/stats")

    threading.Thread(target=uh.run, kwargs={"cfg": us_cfg, "stop_event": stops["us"]}, daemon=True).start()
    _wait_http(f"http://localhost:{PORTS['us_cmd']}/stats")

    yield stops

    for ev in stops.values():
        ev.set()
    time.sleep(0.5)


def test_stats_endpoints_respond(actors):
    for port in [PORTS["crypto_cmd"], PORTS["ds_cmd"], PORTS["router_cmd"], PORTS["us_cmd"]]:
        r = requests.get(f"http://localhost:{port}/stats", timeout=3)
        assert r.status_code == 200
        body = r.json()
        assert "sent_30s" in body


def test_full_roundtrip(actors):
    # upload CSV
    csv_bytes = TEST_CSV.encode("utf-8-sig")
    r = requests.post(
        f"http://localhost:{PORTS['us_cmd']}/upload",
        files={"file": ("test_cases.csv", io.BytesIO(csv_bytes), "text/csv")},
        timeout=5,
    )
    assert r.status_code == 200

    # start sending
    r = requests.get(f"http://localhost:{PORTS['us_cmd']}/start", timeout=5)
    assert r.status_code == 200
    assert r.json()["rows"] == 3

    # wait for all responses
    deadline = time.monotonic() + 10
    results = []
    while time.monotonic() < deadline:
        r = requests.get(f"http://localhost:{PORTS['us_cmd']}/results", timeout=3)
        results = r.json()
        if len(results) >= 3:
            break
        time.sleep(0.3)

    assert len(results) == 3, f"Expected 3 responses, got {len(results)}"


def test_response_codes(actors):
    # re-use results from previous test (upload again to be safe)
    csv_bytes = TEST_CSV.encode("utf-8-sig")
    requests.post(
        f"http://localhost:{PORTS['us_cmd']}/upload",
        files={"file": ("test_cases.csv", io.BytesIO(csv_bytes), "text/csv")},
        timeout=5,
    )
    requests.get(f"http://localhost:{PORTS['us_cmd']}/start", timeout=5)

    deadline = time.monotonic() + 10
    results = []
    while time.monotonic() < deadline:
        r = requests.get(f"http://localhost:{PORTS['us_cmd']}/results", timeout=3)
        results = r.json()
        if len(results) >= 3:
            break
        time.sleep(0.3)

    by_pan = {row.get("2", ""): row for row in results}

    assert by_pan["4111111111111111"]["resp_39"] == "00", "known PAN + crypto True should approve"
    assert by_pan["4222222222222222"]["resp_39"] == "01", "known PAN + crypto False should decline"
    assert by_pan["9999999999999999"]["resp_39"] == "01", "unknown PAN should decline"


def test_approved_has_auth_code(actors):
    r = requests.get(f"http://localhost:{PORTS['us_cmd']}/results", timeout=3)
    results = r.json()
    approved = [row for row in results if row.get("resp_39") == "00"]
    for row in approved:
        assert row.get("resp_38", ""), "approved message must have auth code in field 38"


def test_field47_present_in_response(actors):
    r = requests.get(f"http://localhost:{PORTS['us_cmd']}/results", timeout=3)
    results = r.json()
    for row in results:
        assert "resp_47" in row, "field 47 must be present in all responses"

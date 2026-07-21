import os
import threading
import time

import pytest
import requests

from router import main as router_main
from router.config import CryptoConfig, DownstreamConfig, Framing, RouterConfig, UpstreamConfig
from shared.ims_connect import to_ebcdic
from simulators.crypto_host.main import CryptoHostSim
from simulators.downstream_host.main import DownstreamHostSim
from simulators.upstream_host.main import UpstreamHostSim

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC_PATH = os.path.join(PROJECT_ROOT, "test_spec.json")
PANS_PATH = os.path.join(PROJECT_ROOT, "pans_defined.json")

PORTS = {
    "crypto_cmd": 18082,
    "crypto_rest": 18052,
    "ds_cmd": 18081,
    "ds_port": 18051,
    "router_cmd": 18080,
    "router_upstream_port": 18050,
    "upstream_cmd": 18083,
}


def _wait_ready(port, key=None, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(f"http://127.0.0.1:{port}/stats", timeout=1)
            if resp.status_code == 200:
                data = resp.json()
                if key is None or data.get("connections", {}).get(key):
                    return data
        except requests.RequestException:
            pass
        time.sleep(0.2)
    raise TimeoutError(f"port {port} not ready (key={key})")


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    """Starts crypto/downstream/router/upstream in-thread (not subprocesses) on dedicated
    test ports, wires them together exactly as router_1's real config.json does."""
    crypto = CryptoHostSim(
        {
            "name": "test_crypto",
            "type": "crypto",
            "port": PORTS["crypto_rest"],
            "command_port": PORTS["crypto_cmd"],
            "pans_defined": PANS_PATH,
            "iso_spec": SPEC_PATH,
        }
    )
    crypto.start()

    downstream = DownstreamHostSim(
        {
            "name": "test_downstream",
            "type": "downstream",
            "port": PORTS["ds_port"],
            "command_port": PORTS["ds_cmd"],
            "iso_spec": SPEC_PATH,
            "pans_defined": PANS_PATH,
        }
    )
    downstream.start()

    _wait_ready(PORTS["crypto_cmd"])
    _wait_ready(PORTS["ds_cmd"])

    framing = Framing(header_hex="", length_field_type="ASCII", length_field_bytes=4)
    router_cfg = RouterConfig(
        name="test_router",
        command_port=PORTS["router_cmd"],
        upstream=UpstreamConfig(port=PORTS["router_upstream_port"], framing=framing),
        downstream=DownstreamConfig(
            host="localhost",
            port=PORTS["ds_port"],
            irm_id=to_ebcdic("IRM_ID01", 8),
            client_id=to_ebcdic("CLIENT01", 8),
        ),
        crypto=CryptoConfig(host="localhost", port=PORTS["crypto_rest"]),
        iso_spec=SPEC_PATH,
        log_level="DEBUG",
    )
    stop_event = threading.Event()
    threading.Thread(
        target=router_main.run, kwargs={"cfg": router_cfg, "stop_event": stop_event}, daemon=True
    ).start()
    _wait_ready(PORTS["router_cmd"])

    input_dir = tmp_path_factory.mktemp("upstream_input")
    upstream = UpstreamHostSim(
        {
            "name": "test_upstream",
            "type": "upstream",
            "command_port": PORTS["upstream_cmd"],
            "router": {"host": "localhost", "port": PORTS["router_upstream_port"]},
            "framing": {"header_hex": "", "length_field_type": "ASCII", "length_field_bytes": 4},
            "iso_spec": SPEC_PATH,
            "input_dir": str(input_dir),
            "ping_0800_seconds": 3600,
        }
    )
    upstream.start()
    _wait_ready(PORTS["upstream_cmd"], key="router")
    _wait_ready(PORTS["router_cmd"], key="downstream")

    yield {"input_dir": str(input_dir)}

    stop_event.set()
    crypto.stop_event.set()
    downstream.stop_event.set()
    upstream.stop_event.set()


def _write_csv(path, rows):
    lines = ["2;3;4;11;expected_39"] + rows
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write("\n".join(lines) + "\n")


def test_full_stack_authorization(stack):
    csv_path = os.path.join(stack["input_dir"], "test_cases.csv")
    _write_csv(
        csv_path,
        [
            "4111111111111111;000000;000000000100;000001;00",
            "9999999999999999;000000;000000000200;000002;01",
        ],
    )

    resp = requests.get(f"http://127.0.0.1:{PORTS['upstream_cmd']}/start")
    assert resp.status_code == 200
    assert resp.json()["rows"] == 2

    deadline = time.time() + 10
    results = []
    while time.time() < deadline:
        results = requests.get(f"http://127.0.0.1:{PORTS['upstream_cmd']}/results").json()
        if len(results) >= 2:
            break
        time.sleep(0.3)

    assert len(results) == 2
    by_pan = {r["2"]: r for r in results}
    assert by_pan["4111111111111111"]["resp_39"] == "00"
    assert by_pan["4111111111111111"]["resp_38"]
    assert by_pan["9999999999999999"]["resp_39"] == "01"

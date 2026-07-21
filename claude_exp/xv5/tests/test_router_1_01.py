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
    "crypto_cmd": 18282,
    "crypto_rest": 18252,
    "ds_cmd": 18281,
    "ds_port": 18251,
    "r1_cmd": 18280,
    "r1_upstream": 18250,
    "r2_cmd": 18284,
    "r2_upstream": 18253,
    "u1_cmd": 18283,
    "u2_cmd": 18287,
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
def dual_router_stack(tmp_path_factory):
    """Mirrors router_1 + router_1.01: two router instances sharing one downstream_host and
    crypto_host, each with its own upstream and a distinct downstream client_id."""
    crypto = CryptoHostSim(
        {
            "name": "t2_crypto",
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
            "name": "t2_downstream",
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

    def _router_cfg(name, command_port, upstream_port, client_id):
        return RouterConfig(
            name=name,
            command_port=command_port,
            upstream=UpstreamConfig(port=upstream_port, framing=framing),
            downstream=DownstreamConfig(
                host="localhost",
                port=PORTS["ds_port"],
                irm_id=to_ebcdic("IRM_ID01", 8),
                client_id=to_ebcdic(client_id, 8),
            ),
            crypto=CryptoConfig(host="localhost", port=PORTS["crypto_rest"]),
            iso_spec=SPEC_PATH,
        )

    stop_r1 = threading.Event()
    stop_r2 = threading.Event()
    threading.Thread(
        target=router_main.run,
        kwargs={
            "cfg": _router_cfg("t2_router_1", PORTS["r1_cmd"], PORTS["r1_upstream"], "CLIENT01"),
            "stop_event": stop_r1,
        },
        daemon=True,
    ).start()
    threading.Thread(
        target=router_main.run,
        kwargs={
            "cfg": _router_cfg("t2_router_1_01", PORTS["r2_cmd"], PORTS["r2_upstream"], "CLIENT02"),
            "stop_event": stop_r2,
        },
        daemon=True,
    ).start()
    _wait_ready(PORTS["r1_cmd"], key="downstream")
    _wait_ready(PORTS["r2_cmd"], key="downstream")

    input_dir_1 = tmp_path_factory.mktemp("u1_input")
    input_dir_2 = tmp_path_factory.mktemp("u2_input")

    u1 = UpstreamHostSim(
        {
            "name": "t2_upstream_1",
            "type": "upstream",
            "command_port": PORTS["u1_cmd"],
            "router": {"host": "localhost", "port": PORTS["r1_upstream"]},
            "framing": {"header_hex": "", "length_field_type": "ASCII", "length_field_bytes": 4},
            "iso_spec": SPEC_PATH,
            "input_dir": str(input_dir_1),
            "ping_0800_seconds": 3600,
        }
    )
    u1.start()
    u2 = UpstreamHostSim(
        {
            "name": "t2_upstream_2",
            "type": "upstream",
            "command_port": PORTS["u2_cmd"],
            "router": {"host": "localhost", "port": PORTS["r2_upstream"]},
            "framing": {"header_hex": "", "length_field_type": "ASCII", "length_field_bytes": 4},
            "iso_spec": SPEC_PATH,
            "input_dir": str(input_dir_2),
            "ping_0800_seconds": 3600,
        }
    )
    u2.start()

    _wait_ready(PORTS["u1_cmd"], key="router")
    _wait_ready(PORTS["u2_cmd"], key="router")

    yield

    stop_r1.set()
    stop_r2.set()
    crypto.stop_event.set()
    downstream.stop_event.set()
    u1.stop_event.set()
    u2.stop_event.set()


def test_both_routers_connect_independently(dual_router_stack):
    r1_stats = requests.get(f"http://127.0.0.1:{PORTS['r1_cmd']}/stats").json()
    r2_stats = requests.get(f"http://127.0.0.1:{PORTS['r2_cmd']}/stats").json()

    assert r1_stats["connections"]["downstream"] is True
    assert r1_stats["connections"]["upstream"] is True
    assert r2_stats["connections"]["downstream"] is True
    assert r2_stats["connections"]["upstream"] is True

import threading
import time

import pytest

from router.config import RouterConfig
from router.main import run as router_run
from simulators.crypto_host.main import CryptoHostSim
from simulators.crypto_host.main import load_config as load_crypto_cfg
from simulators.downstream_host.main import DownstreamHost
from simulators.downstream_host.main import load_config as load_ds_cfg
from simulators.upstream_host.main import UpstreamHostSim
from simulators.upstream_host.main import load_config as load_up_cfg

PORTS = {
    "crypto_port": 25502,
    "crypto_cmd": 28582,
    "ds_port": 25501,
    "ds_cmd": 28581,
    "router_cmd": 28580,
    "router_upstream_port": 25500,
    "up_cmd": 28583,
}


@pytest.fixture
def full_stack():
    crypto_cfg = load_crypto_cfg("simulators/crypto_host/config.json")
    crypto_cfg["port"] = PORTS["crypto_port"]
    crypto_cfg["command_port"] = PORTS["crypto_cmd"]
    crypto_sim = CryptoHostSim(crypto_cfg)
    crypto_sim.start()

    ds_cfg = load_ds_cfg("simulators/downstream_host/config.json")
    ds_cfg["port"] = PORTS["ds_port"]
    ds_cfg["command_port"] = PORTS["ds_cmd"]
    ds_sim = DownstreamHost(ds_cfg)
    ds_sim.start()

    time.sleep(0.3)

    router_cfg = RouterConfig.from_file("router/router_1/config.json")
    router_cfg.command_port = PORTS["router_cmd"]
    router_cfg.upstream.port = PORTS["router_upstream_port"]
    router_cfg.downstream.port = PORTS["ds_port"]
    router_cfg.crypto.port = PORTS["crypto_port"]
    router_cfg.reestablish_seconds = 1
    router_cfg.reconnect_jitter_seconds = 0.2

    router_stop = threading.Event()
    router_thread = threading.Thread(
        target=router_run, kwargs={"cfg": router_cfg, "stop_event": router_stop}, daemon=True
    )
    router_thread.start()
    time.sleep(0.5)

    up_cfg = load_up_cfg("simulators/upstream_1/config.json")
    up_cfg["command_port"] = PORTS["up_cmd"]
    up_cfg["router"] = {"host": "localhost", "port": PORTS["router_upstream_port"]}
    up_sim = UpstreamHostSim(up_cfg)
    up_sim.start()
    time.sleep(0.5)

    # Write a known CSV directly rather than relying on the persisted repo fixture —
    # the /upload route mutates this same file, so a previous manual run (or another
    # test) may have left different content behind.
    with open(up_sim._csv_path(), "w", newline="", encoding="utf-8-sig") as f:
        f.write(
            "2;3;4;11;expected_39\n"
            "4111111111111111;000000;000000000100;000001;00\n"
            "4222222222222222;000000;000000000200;000002;01\n"
            "5111111111111111;000000;000000000300;000003;00\n"
            "5222222222222222;000000;000000000400;000004;00\n"
            "9999999999999999;000000;000000000500;000005;01\n"
            "1234567890123456;000000;000000000600;000006;01\n"
        )

    yield up_sim

    router_stop.set()
    ds_sim.stop_event.set()
    crypto_sim.stop_event.set()
    up_sim.stop_event.set()
    router_thread.join(timeout=5)


def test_full_stack_csv_to_field_39(full_stack):
    up_sim = full_stack
    client = up_sim.cmd.app.test_client()

    resp = client.get("/start")
    assert resp.status_code == 200
    assert resp.get_json()["rows"] == 6

    deadline = time.monotonic() + 10
    results = []
    while time.monotonic() < deadline:
        results = client.get("/results").get_json()
        if len(results) >= 6:
            break
        time.sleep(0.2)

    assert len(results) == 6
    by_pan = {r["2"]: r for r in results}

    # known PANs (present in pans_defined.json), no crypto data attached -> approve
    for pan in ("4111111111111111", "4222222222222222", "5111111111111111", "5222222222222222"):
        assert by_pan[pan]["resp_39"] == "00", by_pan[pan]

    # unknown PANs -> decline
    for pan in ("9999999999999999", "1234567890123456"):
        assert by_pan[pan]["resp_39"] == "01", by_pan[pan]

    # STAN restored to the original upstream value on every response
    for r in results:
        assert r["resp_11"] == r["11"]

    # approved transactions carry a non-empty authorization code
    for r in results:
        if r["resp_39"] == "00":
            assert r.get("resp_38")

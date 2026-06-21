import socket
import threading
import time

import requests

from router.config import RouterConfig
from router.main import run as router_run
from simulators.crypto_host.main import CryptoHostSim
from simulators.crypto_host.main import load_config as load_crypto_cfg
from simulators.downstream_host.main import DownstreamHost
from simulators.downstream_host.main import load_config as load_ds_cfg

PORTS = {
    "crypto_port": 25602,
    "crypto_cmd": 28682,
    "ds_port": 25601,
    "ds_cmd": 28681,
    "router_cmd": 28684,
    "router_upstream_port": 25603,
}


def test_router_1_01_connectivity_and_stats():
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

    router_cfg = RouterConfig.from_file("router/router_1.01/config.json")
    router_cfg.command_port = PORTS["router_cmd"]
    router_cfg.upstream.port = PORTS["router_upstream_port"]
    router_cfg.downstream.port = PORTS["ds_port"]
    router_cfg.crypto.port = PORTS["crypto_port"]
    router_cfg.reestablish_seconds = 1
    router_cfg.reconnect_jitter_seconds = 0.2

    stop_event = threading.Event()
    router_thread = threading.Thread(
        target=router_run, kwargs={"cfg": router_cfg, "stop_event": stop_event}, daemon=True
    )
    router_thread.start()
    time.sleep(0.5)

    try:
        resp = requests.get(f"http://127.0.0.1:{router_cfg.command_port}/stats", timeout=3)
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["connections"]["downstream"] is True

        client_sock = socket.create_connection(("127.0.0.1", router_cfg.upstream.port), timeout=3)
        time.sleep(0.3)

        resp = requests.get(f"http://127.0.0.1:{router_cfg.command_port}/stats", timeout=3)
        stats = resp.json()
        assert stats["connections"]["upstream"] is True

        client_sock.close()
    finally:
        stop_event.set()
        ds_sim.stop_event.set()
        crypto_sim.stop_event.set()
        router_thread.join(timeout=5)

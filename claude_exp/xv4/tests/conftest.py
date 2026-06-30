import json
import logging
import os
import threading

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session")
def shared_infra():
    """Start crypto_host and downstream_host once for the entire test session."""
    logging.basicConfig(level=logging.WARNING)

    import sys
    sys.path.insert(0, PROJECT_ROOT)

    from simulators.crypto_host import main as crypto_main
    from simulators.downstream_host import main as ds_main
    from shared.command_server import CommandServer
    from shared.iso_utils import load_spec

    with open(os.path.join(PROJECT_ROOT, "pans_defined.json")) as f:
        pans = json.load(f)
    with open(os.path.join(PROJECT_ROOT, "simulators/crypto_host/config.json")) as f:
        crypto_cfg = json.load(f)
    with open(os.path.join(PROJECT_ROOT, "simulators/downstream_host/config.json")) as f:
        ds_cfg = json.load(f)
    spec = load_spec(os.path.join(PROJECT_ROOT, "test_spec.json"))

    crypto_stop = threading.Event()
    ch = crypto_main.CryptoHost(crypto_cfg, pans)
    ch.stop_event = crypto_stop
    CommandServer(port=crypto_cfg["command_port"], stats=ch.stats, stop_event=crypto_stop).start()
    threading.Thread(target=lambda: ch.run(crypto_cfg["port"]), daemon=True).start()

    ds_stop = threading.Event()
    ds = ds_main.DownstreamHost(ds_cfg, spec, pans)
    ds.stop_event = ds_stop
    CommandServer(port=ds_cfg["command_port"], stats=ds.stats, stop_event=ds_stop).start()
    threading.Thread(target=ds.serve, daemon=True).start()

    import time
    import requests

    def wait_http(port, timeout=10):
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

    assert wait_http(crypto_cfg["command_port"]), "crypto_host didn't start"
    assert wait_http(ds_cfg["command_port"]), "downstream_host didn't start"

    yield {
        "pans": pans,
        "spec": spec,
        "crypto_cfg": crypto_cfg,
        "ds_cfg": ds_cfg,
        "crypto_stop": crypto_stop,
        "ds_stop": ds_stop,
    }

    crypto_stop.set()
    ds_stop.set()

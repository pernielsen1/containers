import json
import os
import tempfile

from router.config import RouterConfig


def test_router_ssl_config_defaults_are_false_and_named():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "router_config.json")
        cert_dir = os.path.join(tmpdir, "certs")
        os.makedirs(cert_dir, exist_ok=True)

        data = {
            "name": "router_test",
            "type": "router",
            "is_active": True,
            "command_port": 8080,
            "upstream": {
                "port": 5000,
                "framing": {
                    "header_hex": "",
                    "length_field_type": "ASCII",
                    "length_field_bytes": 4,
                },
                "ssl_active": False,
                "certfile": "certs/upstream_ssl_active_false_cert.pem",
                "keyfile": "certs/upstream_ssl_active_false_key.pem",
                "cafile": "certs/upstream_ssl_active_false_ca.pem",
            },
            "downstream": {
                "host": "localhost",
                "port": 5001,
                "irm_id": "IRM_ID01",
                "client_id": "CLIENT01",
                "ssl_active": False,
                "certfile": "certs/downstream_ssl_active_false_cert.pem",
                "keyfile": "certs/downstream_ssl_active_false_key.pem",
                "cafile": "certs/downstream_ssl_active_false_ca.pem",
            },
            "crypto": {
                "host": "localhost",
                "port": 5002,
                "plugin_id": "emv-plugin",
                "bearer_token": "dev-token",
                "ssl_active": False,
                "certfile": "certs/crypto_host_ssl_active_false_cert.pem",
                "keyfile": "certs/crypto_host_ssl_active_false_key.pem",
                "cafile": "certs/crypto_host_ssl_active_false_ca.pem",
            },
            "iso_spec": "../../test_spec.json",
        }

        with open(config_path, "w") as f:
            json.dump(data, f)

        cfg = RouterConfig.from_file(config_path)

        assert cfg.upstream.ssl_active is False
        assert cfg.downstream.ssl_active is False
        assert cfg.crypto.ssl_active is False
        assert cfg.upstream.certfile.endswith("upstream_ssl_active_false_cert.pem")
        assert cfg.downstream.certfile.endswith("downstream_ssl_active_false_cert.pem")
        assert cfg.crypto.certfile.endswith("crypto_host_ssl_active_false_cert.pem")

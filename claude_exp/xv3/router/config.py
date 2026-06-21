from __future__ import annotations

import json
import os
from dataclasses import dataclass

from shared.ims_connect import to_ebcdic


@dataclass
class Framing:
    header_hex: str
    length_field_type: str
    length_field_bytes: int

    def to_dict(self) -> dict:
        return {
            "header_hex": self.header_hex,
            "length_field_type": self.length_field_type,
            "length_field_bytes": self.length_field_bytes,
        }


@dataclass
class UpstreamConfig:
    port: int
    framing: Framing
    mode: str = "server"
    host: str = "localhost"
    retry_seconds: int = 5


@dataclass
class DownstreamConfig:
    host: str
    port: int
    irm_id: bytes
    client_id: bytes


@dataclass
class CryptoConfig:
    host: str
    port: int


@dataclass
class RouterConfig:
    name: str
    command_port: int
    upstream: UpstreamConfig
    downstream: DownstreamConfig
    crypto: CryptoConfig
    iso_spec: str
    partner_id: str = None
    log_level: str = "INFO"
    worker_threads: int = 8
    reestablish_seconds: int = 10
    yellow_threshold_seconds: int = 40
    queue_maxsize: int = 1000
    pending_ttl_seconds: int = 30
    crypto_breaker_threshold: int = 5
    crypto_breaker_cooldown_seconds: int = 30
    reconnect_jitter_seconds: float = 2.0
    command_bind_host: str = "127.0.0.1"
    command_auth_token: str = None

    @classmethod
    def from_file(cls, path: str) -> "RouterConfig":
        with open(path, "r") as f:
            data = json.load(f)

        base_dir = os.path.dirname(os.path.abspath(path))

        upstream_data = dict(data["upstream"])
        upstream_data["framing"] = Framing(**upstream_data["framing"])
        upstream = UpstreamConfig(**upstream_data)

        downstream_data = dict(data["downstream"])
        downstream_data["irm_id"] = to_ebcdic(downstream_data["irm_id"], 8)
        downstream_data["client_id"] = to_ebcdic(downstream_data["client_id"], 8)
        downstream = DownstreamConfig(**downstream_data)

        crypto = CryptoConfig(**data["crypto"])

        iso_spec = os.path.normpath(os.path.join(base_dir, data["iso_spec"]))

        extra_kwargs = {
            k: v
            for k, v in data.items()
            if k not in ("upstream", "downstream", "crypto", "iso_spec", "type")
        }

        return cls(
            upstream=upstream,
            downstream=downstream,
            crypto=crypto,
            iso_spec=iso_spec,
            **extra_kwargs,
        )

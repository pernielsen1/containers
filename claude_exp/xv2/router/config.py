"""RouterConfig — typed configuration loaded from config.json.

Maps directly to C++ structs: RouterConfig, UpstreamConfig,
DownstreamConfig, CryptoConfig, Framing.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from shared import ims_connect


@dataclass
class Framing:
    header_hex: str
    length_field_type: str
    length_field_bytes: int

    def to_dict(self) -> dict:
        """Adapter for shared/framing.py which still expects a dict."""
        return {
            "header_hex":        self.header_hex,
            "length_field_type": self.length_field_type,
            "length_field_bytes": self.length_field_bytes,
        }


@dataclass
class UpstreamConfig:
    port: int
    framing: Framing
    mode: str  = "server"      # "server" | "client"
    host: str  = "localhost"
    retry_seconds: int = 5


@dataclass
class DownstreamConfig:
    host: str
    port: int
    irm_id: bytes     # EBCDIC, 8 bytes
    client_id: bytes  # EBCDIC, 8 bytes


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
    iso_spec: str                      # resolved absolute path
    partner_id: str      = None
    log_level: str       = "INFO"
    worker_threads: int  = 8
    reestablish_seconds: int = 10
    yellow_threshold_seconds: int = 40

    @classmethod
    def from_file(cls, path: str) -> RouterConfig:
        config_base = os.path.dirname(os.path.abspath(path))
        with open(path) as f:
            raw = json.load(f)

        up_raw = raw["upstream"]
        upstream = UpstreamConfig(
            port=up_raw["port"],
            framing=Framing(
                header_hex=up_raw["framing"]["header_hex"],
                length_field_type=up_raw["framing"]["length_field_type"],
                length_field_bytes=up_raw["framing"]["length_field_bytes"],
            ),
            mode=up_raw.get("mode", "server"),
            host=up_raw.get("host", "localhost"),
            retry_seconds=up_raw.get("retry_seconds", 5),
        )

        ds_raw = raw["downstream"]
        downstream = DownstreamConfig(
            host=ds_raw["host"],
            port=ds_raw["port"],
            irm_id=ims_connect.to_ebcdic(ds_raw["irm_id"], 8),
            client_id=ims_connect.to_ebcdic(ds_raw["client_id"], 8),
        )

        cr_raw = raw["crypto"]
        crypto = CryptoConfig(host=cr_raw["host"], port=cr_raw["port"])

        return cls(
            name=raw["name"],
            command_port=raw["command_port"],
            upstream=upstream,
            downstream=downstream,
            crypto=crypto,
            iso_spec=os.path.normpath(os.path.join(config_base, raw["iso_spec"])),
            partner_id=raw.get("partner_id"),
            log_level=raw.get("log_level", "INFO"),
            worker_threads=raw.get("worker_threads", 8),
            reestablish_seconds=raw.get("reestablish_seconds", 10),
            yellow_threshold_seconds=raw.get("yellow_threshold_seconds", 40),
        )

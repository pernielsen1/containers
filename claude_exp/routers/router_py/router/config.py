import json
import os
from dataclasses import dataclass
from typing import Optional

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
    ssl_active: bool = False
    certfile: Optional[str] = None
    keyfile: Optional[str] = None
    cafile: Optional[str] = None


@dataclass
class DownstreamConfig:
    host: str
    port: int
    irm_id: bytes
    client_id: bytes
    ssl_active: bool = False
    certfile: Optional[str] = None
    keyfile: Optional[str] = None
    cafile: Optional[str] = None


@dataclass
class CryptoConfig:
    host: str
    port: int
    plugin_id: str
    bearer_token: str
    ssl_active: bool = False
    certfile: Optional[str] = None
    keyfile: Optional[str] = None
    cafile: Optional[str] = None


@dataclass
class RouterConfig:
    name: str
    command_port: int
    upstream: UpstreamConfig
    downstream: DownstreamConfig
    crypto: CryptoConfig
    iso_spec: str
    upstream_iso_spec: Optional[str] = None
    partner_id: Optional[str] = None
    log_level: str = "INFO"
    worker_threads: int = 8
    response_worker_threads: int = 8
    reestablish_seconds: int = 10
    yellow_threshold_seconds: int = 40
    queue_maxsize: int = 1000
    pending_ttl_seconds: int = 30
    crypto_breaker_threshold: int = 5
    crypto_breaker_cooldown_seconds: int = 30
    # Response-leg (validate_0110) crypto calls get their own, much shorter timeout than the
    # request leg's default (CryptoClient's own 5.0s default, used for validate_0100) - see
    # router/session.py and briefs/resilience_v2.md's "fire and forget" framing. 0.2s matches
    # this dev laptop's own observed latency headroom; a real deployment (briefs' own estimate:
    # 50-75ms typical crypto_host RTT) should tune this down accordingly.
    crypto_response_timeout_seconds: float = 0.2
    reconnect_jitter_seconds: float = 2.0
    command_bind_host: str = "127.0.0.1"
    command_auth_token: Optional[str] = None

    @staticmethod
    def _resolve_path(base_dir: str, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if os.path.isabs(value):
            return value
        return os.path.normpath(os.path.join(base_dir, value))

    @classmethod
    def from_file(cls, path: str) -> "RouterConfig":
        with open(path) as f:
            data = json.load(f)
        base_dir = os.path.dirname(os.path.abspath(path))

        framing_data = data["upstream"]["framing"]
        framing = Framing(
            header_hex=framing_data.get("header_hex", ""),
            length_field_type=framing_data["length_field_type"],
            length_field_bytes=framing_data["length_field_bytes"],
        )
        upstream_cfg = data["upstream"]
        upstream = UpstreamConfig(
            port=upstream_cfg["port"],
            framing=framing,
            mode=upstream_cfg.get("mode", "server"),
            host=upstream_cfg.get("host", "localhost"),
            retry_seconds=upstream_cfg.get("retry_seconds", 5),
            ssl_active=bool(upstream_cfg.get("ssl_active", False)),
            certfile=cls._resolve_path(base_dir, upstream_cfg.get("certfile")),
            keyfile=cls._resolve_path(base_dir, upstream_cfg.get("keyfile")),
            cafile=cls._resolve_path(base_dir, upstream_cfg.get("cafile")),
        )

        ds = data["downstream"]
        downstream = DownstreamConfig(
            host=ds["host"],
            port=ds["port"],
            irm_id=to_ebcdic(ds["irm_id"], 8),
            client_id=to_ebcdic(ds["client_id"], 8),
            ssl_active=bool(ds.get("ssl_active", False)),
            certfile=cls._resolve_path(base_dir, ds.get("certfile")),
            keyfile=cls._resolve_path(base_dir, ds.get("keyfile")),
            cafile=cls._resolve_path(base_dir, ds.get("cafile")),
        )

        crypto_cfg = data["crypto"]
        crypto = CryptoConfig(
            host=crypto_cfg["host"],
            port=crypto_cfg["port"],
            plugin_id=crypto_cfg["plugin_id"],
            bearer_token=crypto_cfg["bearer_token"],
            ssl_active=bool(crypto_cfg.get("ssl_active", False)),
            certfile=cls._resolve_path(base_dir, crypto_cfg.get("certfile")),
            keyfile=cls._resolve_path(base_dir, crypto_cfg.get("keyfile")),
            cafile=cls._resolve_path(base_dir, crypto_cfg.get("cafile")),
        )

        iso_spec = os.path.normpath(os.path.join(base_dir, data["iso_spec"]))
        upstream_iso_spec = (
            os.path.normpath(os.path.join(base_dir, data["upstream_iso_spec"]))
            if data.get("upstream_iso_spec")
            else None
        )

        # Every JSON key consumed explicitly above, or that is monitor-only metadata with no
        # RouterConfig field, must be excluded here or RouterConfig(**extra_kwargs) below raises
        # TypeError: __init__() got an unexpected keyword argument.
        extra_kwargs = {
            k: v
            for k, v in data.items()
            if k
            not in (
                "upstream",
                "downstream",
                "crypto",
                "iso_spec",
                "upstream_iso_spec",
                "type",
                "is_active",
            )
        }

        return cls(
            upstream=upstream,
            downstream=downstream,
            crypto=crypto,
            iso_spec=iso_spec,
            upstream_iso_spec=upstream_iso_spec,
            **extra_kwargs,
        )

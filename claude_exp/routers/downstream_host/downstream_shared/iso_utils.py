import json
import logging

import iso8583


def load_spec(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def build_0800(spec: dict) -> bytes:
    encoded, _ = iso8583.encode({"t": "0800", "24": "100"}, spec)
    return bytes(encoded)


def build_0810(f24: str, spec: dict) -> bytes:
    encoded, _ = iso8583.encode({"t": "0810", "24": f24}, spec)
    return bytes(encoded)


def f47_encode(data: dict) -> str:
    return json.dumps(data, separators=(",", ":"))


def f47_decode(value: str) -> dict:
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


def hex_dump(label: str, data: bytes, logger: logging.Logger) -> None:
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("%s: %s", label, data.hex())

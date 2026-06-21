import json
import logging

import iso8583


def load_spec(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def build_0800(spec) -> bytes:
    s, _ = iso8583.encode({"t": "0800", "24": "100"}, spec)
    return bytes(s)


def build_0810(f24: str, spec) -> bytes:
    s, _ = iso8583.encode({"t": "0810", "24": f24}, spec)
    return bytes(s)


def f47_encode(data: dict) -> str:
    return json.dumps(data, separators=(",", ":"))


def f47_decode(value: str) -> dict:
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def hex_dump(label, data, logger: logging.Logger) -> None:
    if logger.isEnabledFor(logging.DEBUG):
        hex_str = data.hex() if isinstance(data, (bytes, bytearray)) else str(data)
        logger.debug("%s: %s", label, hex_str)

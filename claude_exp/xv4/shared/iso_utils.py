import json
import logging
import iso8583
import iso8583.specs


def load_spec(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def build_0800(spec) -> bytes:
    msg = {"t": "0800", "24": "100"}
    encoded, _ = iso8583.encode(msg, spec)
    return encoded


def build_0810(f24: str, spec) -> bytes:
    msg = {"t": "0810", "24": f24}
    encoded, _ = iso8583.encode(msg, spec)
    return encoded


def f47_encode(data: dict) -> str:
    return json.dumps(data, separators=(",", ":"))


def f47_decode(value: str) -> dict:
    try:
        return json.loads(value)
    except Exception:
        return {}


def hex_dump(label, data, logger):
    if logger.isEnabledFor(logging.DEBUG):
        hex_str = data.hex()
        logger.debug("%s [%d bytes]: %s", label, len(data), hex_str)

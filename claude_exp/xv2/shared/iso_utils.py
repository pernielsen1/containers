import json
import logging

import iso8583 as _iso8583


def load_spec(path):
    with open(path) as f:
        return json.load(f)


def build_0800(spec) -> bytes:
    msg = {"t": "0800", "24": "100"}
    encoded, _ = _iso8583.encode(msg, spec=spec)
    return encoded


def build_0810(f24: str, spec) -> bytes:
    msg = {"t": "0810", "24": f24}
    encoded, _ = _iso8583.encode(msg, spec=spec)
    return encoded


def f47_encode(data):
    return json.dumps(data, separators=(",", ":"))


def hex_dump(label, data, logger):
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("%s [%d bytes] %s", label, len(data), data.hex(" "))


def f47_decode(value):
    if not value:
        return {}
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}

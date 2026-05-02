import json
import logging


def load_spec(path):
    with open(path) as f:
        return json.load(f)


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

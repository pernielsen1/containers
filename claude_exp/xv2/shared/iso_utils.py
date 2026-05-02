import json


def load_spec(path):
    with open(path) as f:
        return json.load(f)


def f47_encode(data):
    return json.dumps(data, separators=(",", ":"))


def f47_decode(value):
    if not value:
        return {}
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}

"""In-memory key store. Loaded from JSON at startup; derived keys added at runtime."""

import base64
import json
from pathlib import Path

_store: dict[str, bytes] = {}


def load(path: str | Path) -> None:
    data = json.loads(Path(path).read_text())
    for name, b64val in data.items():
        _store[name] = base64.b64decode(b64val)


def get(token_id: str) -> bytes | None:
    return _store.get(token_id)


def put(token_id: str, value: bytes) -> None:
    _store[token_id] = value


def all_tokens() -> list[str]:
    return list(_store.keys())

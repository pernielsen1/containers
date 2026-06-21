import time

import pytest
import requests

from router.config import CryptoConfig
from router.crypto_client import CryptoClient


def _unused_port_client(**kwargs):
    cfg = CryptoConfig(host="127.0.0.1", port=1)  # port 1 — connection refused
    return CryptoClient(cfg, **kwargs)


def test_breaker_opens_after_threshold_consecutive_failures():
    client = _unused_port_client(breaker_threshold=3, breaker_cooldown_seconds=10)

    for _ in range(3):
        result = client.validate("validate_0100", "4111111111111111", "orig")
        assert result == ""

    assert client._failure_count == 3
    assert client._open_until > time.monotonic()


def test_breaker_short_circuits_without_http_call_while_open():
    client = _unused_port_client(breaker_threshold=1, breaker_cooldown_seconds=10)

    result = client.validate("validate_0100", "pan", "orig")
    assert result == ""
    assert client._open_until > time.monotonic()

    def boom(*args, **kwargs):
        raise AssertionError("HTTP call should not happen while breaker is open")

    client.session.post = boom
    result2 = client.validate("validate_0100", "pan", "orig")
    assert result2 == ""


def test_breaker_closes_after_cooldown_and_retries(monkeypatch):
    client = _unused_port_client(breaker_threshold=1, breaker_cooldown_seconds=0.2)

    result = client.validate("validate_0100", "pan", "orig")
    assert result == ""
    assert client._open_until > time.monotonic()

    time.sleep(0.3)

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"f47": "enriched"}

    called = {"n": 0}

    def fake_post(*args, **kwargs):
        called["n"] += 1
        return FakeResponse()

    monkeypatch.setattr(client.session, "post", fake_post)

    result2 = client.validate("validate_0100", "pan", "orig")
    assert result2 == "enriched"
    assert called["n"] == 1
    assert client._failure_count == 0


def test_validate_returns_f47_unchanged_path_when_caller_guards_truthy():
    # validate() itself returns "" on error; callers in the dispatcher only overwrite
    # fwd["47"] when the result is truthy, which is what keeps the original f47 intact.
    client = _unused_port_client(breaker_threshold=5, breaker_cooldown_seconds=10)
    result = client.validate("validate_0100", "pan", "original-f47")
    assert result == ""

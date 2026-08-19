import base64
import json
import time
from unittest.mock import MagicMock

from router.crypto_client import CryptoClient


class _UnreachableCfg:
    host = "127.0.0.1"
    port = 19999  # nothing listens here
    plugin_id = "test-plugin"
    bearer_token = "test-token"


class _FakeResponse:
    def __init__(self, status: int, body: bytes):
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body


class _FakeConnection:
    """Stands in for http.client.HTTPConnection: records calls, returns a canned response."""

    def __init__(self, response: _FakeResponse):
        self.response = response
        self.request_count = 0

    def request(self, method, path, body=None, headers=None):
        self.request_count += 1

    def getresponse(self):
        return self.response

    def close(self):
        pass


def _success_response() -> _FakeResponse:
    envelope = json.dumps({"f47": '{"response_code":"00"}'})
    b64_envelope = base64.b64encode(envelope.encode("utf-8")).decode("ascii")
    return _FakeResponse(200, json.dumps(b64_envelope).encode("utf-8"))


def test_breaker_opens_after_threshold_failures_and_short_circuits():
    client = CryptoClient(_UnreachableCfg(), breaker_threshold=3, breaker_cooldown_seconds=2)

    for _ in range(3):
        assert client.validate("validate_0100", "4111111111111111", "{}") == ""

    assert time.time() < client._open_until

    client._get_connection = MagicMock(side_effect=AssertionError("should not be called while breaker is open"))
    assert client.validate("validate_0100", "4111111111111111", "{}") == ""
    client._get_connection.assert_not_called()


def test_breaker_closes_after_cooldown_and_retries():
    client = CryptoClient(_UnreachableCfg(), breaker_threshold=1, breaker_cooldown_seconds=0.3)

    client.validate("validate_0100", "4111111111111111", "{}")
    assert time.time() < client._open_until

    time.sleep(0.4)

    fake_conn = _FakeConnection(_success_response())
    client._thread_local.conn = fake_conn
    client.validate("validate_0100", "4111111111111111", "{}")
    assert fake_conn.request_count == 1


def test_successful_call_resets_failure_counter():
    client = CryptoClient(_UnreachableCfg(), breaker_threshold=2, breaker_cooldown_seconds=5)
    client.validate("validate_0100", "4111111111111111", "{}")
    assert client._failure_count == 1

    client._thread_local.conn = _FakeConnection(_success_response())

    result = client.validate("validate_0100", "4111111111111111", "{}")
    assert result == '{"response_code":"00"}'
    assert client._failure_count == 0

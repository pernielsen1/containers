import time
from unittest.mock import MagicMock

from router.crypto_client import CryptoClient


class _UnreachableCfg:
    host = "127.0.0.1"
    port = 19999  # nothing listens here


def test_breaker_opens_after_threshold_failures_and_short_circuits():
    client = CryptoClient(_UnreachableCfg(), breaker_threshold=3, breaker_cooldown_seconds=2)

    for _ in range(3):
        assert client.validate("validate_0100", "4111111111111111", "{}") == ""

    assert time.time() < client._open_until

    client._session.post = MagicMock(side_effect=AssertionError("should not be called while breaker is open"))
    assert client.validate("validate_0100", "4111111111111111", "{}") == ""
    client._session.post.assert_not_called()


def test_breaker_closes_after_cooldown_and_retries():
    client = CryptoClient(_UnreachableCfg(), breaker_threshold=1, breaker_cooldown_seconds=0.3)

    client.validate("validate_0100", "4111111111111111", "{}")
    assert time.time() < client._open_until

    time.sleep(0.4)

    original_post = client._session.post
    call_count = {"n": 0}

    def spy_post(*args, **kwargs):
        call_count["n"] += 1
        return original_post(*args, **kwargs)

    client._session.post = spy_post
    client.validate("validate_0100", "4111111111111111", "{}")
    assert call_count["n"] == 1


def test_successful_call_resets_failure_counter():
    client = CryptoClient(_UnreachableCfg(), breaker_threshold=2, breaker_cooldown_seconds=5)
    client.validate("validate_0100", "4111111111111111", "{}")
    assert client._failure_count == 1

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"f47": '{"response_code":"00"}'}
    client._session.post = MagicMock(return_value=fake_response)

    result = client.validate("validate_0100", "4111111111111111", "{}")
    assert result == '{"response_code":"00"}'
    assert client._failure_count == 0

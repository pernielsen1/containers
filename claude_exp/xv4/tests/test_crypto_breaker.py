import sys
import os
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import MagicMock, patch
from router.crypto_client import CryptoClient


class FakeCryptoConfig:
    host = "127.0.0.1"
    port = 19999  # nothing listening here


def test_breaker_opens_after_threshold():
    cfg = FakeCryptoConfig()
    client = CryptoClient(cfg, breaker_threshold=3, breaker_cooldown_seconds=60)
    # Each call will fail (no server)
    for _ in range(3):
        result = client.validate("validate_0100", "4111111111111111", '{"message_type":"0100"}')

    # Breaker should now be open — verify it short-circuits without HTTP call
    with patch.object(client._session, "post") as mock_post:
        client.validate("validate_0100", "4111111111111111", '{}')
        mock_post.assert_not_called()


def test_breaker_returns_original_f47_when_open():
    cfg = FakeCryptoConfig()
    client = CryptoClient(cfg, breaker_threshold=2, breaker_cooldown_seconds=60)
    f47 = '{"message_type":"0100","response_code":"00"}'
    for _ in range(2):
        client.validate("validate_0100", "4111111111111111", f47)
    result = client.validate("validate_0100", "4111111111111111", f47)
    assert result == f47


def test_breaker_closes_after_cooldown():
    cfg = FakeCryptoConfig()
    client = CryptoClient(cfg, breaker_threshold=2, breaker_cooldown_seconds=0)
    for _ in range(2):
        client.validate("validate_0100", "4111111111111111", "{}")

    # Immediately after opening with cooldown=0, it should be open
    # but after a tiny wait it can be tried again
    time.sleep(0.05)

    # Mock a successful response
    with patch.object(client._session, "post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.raise_for_status = lambda: None
        mock_post.return_value.json.return_value = {"f47": '{"response_code":"00"}'}
        result = client.validate("validate_0100", "4111111111111111", "{}")
        mock_post.assert_called_once()
        assert result == '{"response_code":"00"}'


def test_success_resets_failure_counter():
    cfg = FakeCryptoConfig()
    client = CryptoClient(cfg, breaker_threshold=5, breaker_cooldown_seconds=60)

    # Cause 3 failures
    for _ in range(3):
        client.validate("validate_0100", "4111111111111111", "{}")

    # Now succeed
    with patch.object(client._session, "post") as mock_post:
        mock_post.return_value.raise_for_status = lambda: None
        mock_post.return_value.json.return_value = {"f47": '{}'}
        client.validate("validate_0100", "4111111111111111", "{}")

    # Counter should be reset — 2 more failures shouldn't open the breaker
    for _ in range(2):
        client.validate("validate_0100", "4111111111111111", "{}")

    with patch.object(client._session, "post") as mock_post:
        mock_post.return_value.raise_for_status = lambda: None
        mock_post.return_value.json.return_value = {"f47": '{}'}
        client.validate("validate_0100", "4111111111111111", "{}")
        mock_post.assert_called_once()

import base64
import json
import time
from unittest.mock import MagicMock

from router.crypto_client import CryptoClient, _CachedConnection


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


class _DyingConnection:
    """Stands in for a connection whose socket is already dead (killed peer, expired keep-alive)
    - every request() raises, same as a real closed/reset socket would."""

    def __init__(self):
        self.request_count = 0
        self.closed = False

    def request(self, method, path, body=None, headers=None):
        self.request_count += 1
        raise OSError("Connection reset by peer")

    def getresponse(self):
        raise AssertionError("getresponse() should not be reached - request() already raised")

    def close(self):
        self.closed = True


def _success_response() -> _FakeResponse:
    envelope = json.dumps({"f47": '{"response_code":"00"}'})
    b64_envelope = base64.b64encode(envelope.encode("utf-8")).decode("ascii")
    return _FakeResponse(200, json.dumps(b64_envelope).encode("utf-8"))


def test_breaker_opens_after_threshold_failures_and_short_circuits():
    client = CryptoClient(_UnreachableCfg(), breaker_threshold=3, breaker_cooldown_seconds=2)

    for _ in range(3):
        assert client.validate("validate_0100", "4111111111111111", "{}") is None

    assert time.time() < client._open_until

    client._get_connection = MagicMock(side_effect=AssertionError("should not be called while breaker is open"))
    assert client.validate("validate_0100", "4111111111111111", "{}") is None
    client._get_connection.assert_not_called()


def test_breaker_closes_after_cooldown_and_retries():
    client = CryptoClient(_UnreachableCfg(), breaker_threshold=1, breaker_cooldown_seconds=0.3)

    client.validate("validate_0100", "4111111111111111", "{}")
    assert time.time() < client._open_until

    time.sleep(0.4)

    # Opening the breaker bumped _generation, so the connection this thread cached before the
    # outage is presumed dead and never reused (see CryptoClient._generation) - stub
    # _new_connection() rather than planting a connection directly, so the call gets one the way
    # a real post-recovery call would: freshly built.
    fake_conn = _FakeConnection(_success_response())
    client._new_connection = lambda: fake_conn
    client.validate("validate_0100", "4111111111111111", "{}")
    assert fake_conn.request_count == 1


def test_successful_call_resets_failure_counter():
    client = CryptoClient(_UnreachableCfg(), breaker_threshold=2, breaker_cooldown_seconds=5)
    client.validate("validate_0100", "4111111111111111", "{}")
    assert client._failure_count == 1

    client._thread_local.cached = _CachedConnection(
        _FakeConnection(_success_response()), client._generation, time.monotonic()
    )

    result = client.validate("validate_0100", "4111111111111111", "{}")
    assert result == '{"response_code":"00"}'
    assert client._failure_count == 0


def test_dead_connection_is_forgotten_not_retried_inline():
    """The whole point of _generation: a failed call is never rescued by retrying on a fresh
    connection within the same validate() call - it's just forgotten, so the failure is real and
    counts toward the breaker, and the *next* call (this thread's or another's) starts clean."""
    client = CryptoClient(_UnreachableCfg(), breaker_threshold=5, breaker_cooldown_seconds=5)
    dying = _DyingConnection()
    client._thread_local.cached = _CachedConnection(dying, client._generation, time.monotonic())

    result = client.validate("validate_0100", "4111111111111111", "{}")

    assert result is None
    assert dying.request_count == 1  # exactly one attempt - no inline retry
    assert dying.closed  # forgotten, not left cached for reuse
    assert client._thread_local.cached is None
    assert client._failure_count == 1


def test_reset_breaker_closes_immediately_and_invalidates_cached_connections():
    """reset_breaker() is for a caller that has *externally confirmed* the service is back and
    doesn't want to wait out the breaker's own cooldown clock (see CryptoClient.reset_breaker
    docstring) - it must close the breaker right away, not just eventually, and must invalidate
    already-cached connections the same way a normal open/close cycle does."""
    client = CryptoClient(_UnreachableCfg(), breaker_threshold=1, breaker_cooldown_seconds=300)

    client.validate("validate_0100", "4111111111111111", "{}")
    assert client._failure_count == 1
    assert time.time() < client._open_until  # breaker open, would stay open for 300s untouched
    generation_after_trip = client._generation

    client.reset_breaker()

    assert client._failure_count == 0
    assert client._open_until == 0.0
    assert client._generation == generation_after_trip + 1

    fake_conn = _FakeConnection(_success_response())
    client._new_connection = lambda: fake_conn
    result = client.validate("validate_0100", "4111111111111111", "{}")
    assert result == '{"response_code":"00"}'
    assert fake_conn.request_count == 1


def test_cached_connection_discarded_once_breaker_opens():
    """A connection cached by this thread before crypto_host died must never be handed back out
    once the breaker has opened - even though *this* thread never personally saw a failure.
    threading.local() means the thread that trips the breaker can't reach into other threads'
    cached sockets to close them directly, so staleness is tracked via _generation and checked
    before any request is attempted, not discovered by trying and failing."""
    client = CryptoClient(_UnreachableCfg(), breaker_threshold=1, breaker_cooldown_seconds=5)
    stale = _FakeConnection(_success_response())
    client._thread_local.cached = _CachedConnection(stale, 0, time.monotonic())  # pre-outage generation

    # Simulates another thread having just tripped the breaker - this thread hasn't made a call
    # since, so its cache is still generation 0.
    client._generation = 1

    fresh = _FakeConnection(_success_response())
    client._new_connection = lambda: fresh

    conn = client._get_connection()

    assert conn is fresh
    assert stale.request_count == 0  # never reused
    assert client._thread_local.cached.generation == 1


def test_cached_connection_discarded_after_idle_timeout():
    """A connection can go stale without any breaker event at all: crypto_host (cpp-httplib)
    closes idle keep-alive connections on its own timeout (5s default), independent of whether
    this client ever saw a failure. Reproduced directly against the real crypto_host container -
    the first request after any ~5s+ traffic lull (e.g. a soak's tail-settle sleep between stress
    windows) failed with SSLEOFError on a reused connection. _get_connection() must proactively
    discard a connection that's been idle past idle_timeout_seconds, the same way it discards one
    from a stale generation - anticipated, not discovered by failing first."""
    client = CryptoClient(_UnreachableCfg(), breaker_threshold=5, breaker_cooldown_seconds=5, idle_timeout_seconds=0.05)
    stale = _FakeConnection(_success_response())
    # well past the 0.05s idle timeout
    client._thread_local.cached = _CachedConnection(stale, client._generation, time.monotonic() - 1.0)

    fresh = _FakeConnection(_success_response())
    client._new_connection = lambda: fresh

    conn = client._get_connection()

    assert conn is fresh
    assert stale.request_count == 0  # never reused


def test_recently_used_connection_is_not_discarded():
    """The idle-timeout check must not evict a connection that's still within its idle budget -
    only genuinely idle-too-long connections get discarded."""
    client = CryptoClient(_UnreachableCfg(), breaker_threshold=5, breaker_cooldown_seconds=5, idle_timeout_seconds=10.0)
    active = _FakeConnection(_success_response())
    client._thread_local.cached = _CachedConnection(active, client._generation, time.monotonic())

    conn = client._get_connection()

    assert conn is active

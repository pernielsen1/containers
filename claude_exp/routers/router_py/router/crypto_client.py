import base64
import http.client
import json
import logging
import threading
import time

from shared.log_throttle import ThrottledLogger
from shared.ssl_utils import build_client_context

logger = logging.getLogger(__name__)


class _CachedConnection:
    """One thread's cached HTTPConnection plus the bookkeeping that decides whether it's still
    usable - bundled into a single object instead of three loose thread-local attributes
    (conn/conn_generation/last_used) kept in sync by hand across _get_connection/_forget_connection.
    Same idiom as upstream_host/main.py's _Connection: a cached resource that can go stale is
    modeled as one object with its own validity state, not scattered fields."""
    __slots__ = ("conn", "generation", "last_used")

    def __init__(self, conn, generation, last_used):
        self.conn = conn
        self.generation = generation
        self.last_used = last_used


# briefs/resilience_v2.md's fail_percentage/crypto-kill chaos scenarios turn a genuine crypto_host
# failure from a rare event into a sustained, high-volume one (10% of steady traffic, or ~100% of
# traffic for the duration of a kill) - unthrottled this floods stdout the same way unthrottled
# advice/reversal traffic did on the upstream_host side (see that side's log_throttle.py).
_throttled = ThrottledLogger(logger, every=200)


class CryptoClient:
    """Fortanix-shaped crypto client: POST /sys/v1/plugins/{plugin_id}, bearer auth, base64
    response. Wired this way so swapping in a real Fortanix DSM tenant is a config/URL change,
    not a rewrite - matches CryptoClient.java / crypto_client.cpp.

    Uses stdlib http.client, not requests: a routers soak test (2026-08-19) isolated this leg
    and found requests/urllib3's per-call overhead (PreparedRequest/adapter/pool-manager
    machinery) scales the GIL-serialized cost of a validate() call directly with concurrent
    caller count - measured p50 doubling with every doubling of concurrent threads (1 thread
    3.6ms -> 8 threads 32ms) while crypto_host's own CPU stayed under 20% and the host stayed
    71% idle, i.e. the bottleneck was Python-side call overhead, not the network or server.
    Swapping to http.client.HTTPSConnection cut that per-call cost by ~3-4x at every
    concurrency level in the same isolated test (8 threads: 32ms -> 8ms p50) - the scaling
    with thread count is still there (inherent to N GIL-bound threads sharing one core's worth
    of Python bytecode time) but the constant it scales from is now far smaller.
    """

    def __init__(
        self,
        cfg,
        breaker_threshold: int = 5,
        breaker_cooldown_seconds: int = 30,
        timeout_seconds: float = 5.0,
        idle_timeout_seconds: float = 4.0,
    ):
        self._ssl_active = getattr(cfg, "ssl_active", False)
        # Request-leg (validate_0100) and response-leg (validate_0110) callers use separate
        # CryptoClient instances with separate timeouts (see router/session.py) - the response
        # leg deliberately runs much shorter (briefs/resilience_v2.md: "fire and forget... no one
        # cares about the result anymore" once downstream has already answered) so a stuck crypto
        # call can't tie up a response-worker thread for the full default timeout.
        self._timeout_seconds = timeout_seconds
        self._host = cfg.host
        self._port = cfg.port
        self._path = f"/sys/v1/plugins/{cfg.plugin_id}"
        self._bearer_token = cfg.bearer_token
        self._ssl_context = (
            build_client_context(
                certfile=getattr(cfg, "certfile", None),
                keyfile=getattr(cfg, "keyfile", None),
                cafile=getattr(cfg, "cafile", None),
            )
            if self._ssl_active
            else None
        )
        # One persistent HTTPConnection per calling thread, not one shared across all
        # worker_threads + response_worker_threads callers - see class docstring. Matches
        # CryptoClient.java's ThreadLocal<HttpClient> and crypto_client.cpp's thread_local
        # httplib::Client.
        self._thread_local = threading.local()
        self._breaker_threshold = breaker_threshold
        self._breaker_cooldown_seconds = breaker_cooldown_seconds
        self._lock = threading.Lock()
        self._failure_count = 0
        self._open_until = 0.0
        # Bumped every time the breaker opens - see validate()'s failure branch. A thread's
        # cached connection is only trusted if it was built under the *current* generation;
        # threading.local() means one thread can't reach into another thread's cached socket to
        # close it directly when crypto_host dies, so instead every thread checks its own
        # connection's generation the next time it needs one and discards it on mismatch, before
        # ever trying to use it - see _get_connection(). Never retried inline (see _send()): a
        # dead connection is forgotten and the call fails, on the theory that recovering *this*
        # transaction isn't the goal - having a fresh connection ready for the next one is.
        self._generation = 0
        # Separate from the generation check above: a connection can go stale without any breaker
        # event at all, just from an ordinary traffic lull - crypto_host (cpp-httplib) closes a
        # keep-alive connection after its own idle timeout (5s default, not overridden - only
        # keep_alive_max_count was raised, see crypto_host_main.cpp's NOTE), and a thread-local
        # HTTPSConnection has no way to learn that from the client side short of trying it.
        # Reproduced directly: after any ~5s+ gap in traffic (e.g. resilience soak's tail-settle
        # sleep between stress windows), the next reuse of an idle worker thread's cached
        # connection fails with SSLEOFError on both validate_0100 and validate_0110 - silent on
        # the request leg (fails open) but drops the response entirely on the response leg, so a
        # perfectly healthy crypto_host looks like an outage right after every lull. Tracking
        # last-used time per thread and discarding proactively before crypto_host's own timeout
        # can hit applies the same "anticipate staleness, don't discover it by failing first"
        # principle the generation check already uses, just against a timer instead of an event.
        self._idle_timeout_seconds = idle_timeout_seconds

    def _new_connection(self) -> http.client.HTTPConnection:
        if self._ssl_active:
            return http.client.HTTPSConnection(
                self._host, self._port, context=self._ssl_context, timeout=self._timeout_seconds
            )
        return http.client.HTTPConnection(self._host, self._port, timeout=self._timeout_seconds)

    def _get_connection(self) -> http.client.HTTPConnection:
        with self._lock:
            current_generation = self._generation
        now = time.monotonic()
        cached = getattr(self._thread_local, "cached", None)
        if cached is not None:
            idle_too_long = (now - cached.last_used) > self._idle_timeout_seconds
            if cached.generation != current_generation or idle_too_long:
                cached.conn.close()
                cached = None
        if cached is None:
            cached = _CachedConnection(self._new_connection(), current_generation, now)
            self._thread_local.cached = cached
        else:
            cached.last_used = now
        return cached.conn

    def _forget_connection(self) -> None:
        cached = getattr(self._thread_local, "cached", None)
        if cached is not None:
            cached.conn.close()
        self._thread_local.cached = None

    def _send(self, body: str, headers: dict) -> bytes:
        # Never retries a failed connection inline - see class docstring's _generation note. A
        # keep-alive connection can go bad between soak-test phases (idle timeout, or crypto_host
        # itself dying) or from ordinary server-side recycling (keep_alive_max_count); either way
        # this call is forgotten, not rescued, so the next call - this thread's or another's -
        # starts from a known-fresh connection instead of inheriting a guessing game.
        conn = self._get_connection()
        try:
            conn.request("POST", self._path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
        except (OSError, http.client.HTTPException):
            self._forget_connection()
            raise

        if resp.status >= 400:
            raise http.client.HTTPException(f"HTTP {resp.status}: {data[:200]!r}")
        return data

    def validate(self, endpoint: str, pan: str, f47: str, router_stan: str = "") -> str | None:
        """Returns the enriched f47 on success (possibly "" if crypto_host genuinely had
        nothing to add), or None on any failure (breaker open or HTTP error) - callers only
        overwrite their working f47 when this return value is truthy, so any failure or no-op
        path leaves the original f47 untouched; a caller that needs to distinguish "no-op
        success" from "failure" (see dispatcher.handle_response's 0110 leg, which drops the
        message on a genuine failure rather than forwarding unvalidated) checks for None
        specifically. Handles the Fortanix PluginOutput envelope: response body is a
        base64-encoded JSON string, which we decode to reach the inner {"f47": ...} object.

        router_stan is passed through so crypto_host's own logs can be joined with this
        router's logs on the same transaction - it's not part of the Fortanix plugin contract,
        just an extra field crypto_host echoes into its log lines."""
        with self._lock:
            if time.time() < self._open_until:
                return None

        try:
            body = json.dumps({"operation": endpoint, "f2": pan, "f47": f47, "router_stan": router_stan})
            headers = {
                "Authorization": f"Bearer {self._bearer_token}",
                "Content-Type": "application/json",
            }
            data = self._send(body, headers)
            decoded = base64.b64decode(json.loads(data)).decode("utf-8")
            result = json.loads(decoded).get("f47", "")
        except Exception as e:
            _throttled.log(
                logging.WARNING,
                f"crypto_call_failed:{endpoint}",
                "crypto_host %s call failed (router_stan=%s): %s",
                endpoint, router_stan, e, extra={"router_stan": router_stan},
            )
            with self._lock:
                self._failure_count += 1
                if self._failure_count >= self._breaker_threshold:
                    self._open_until = time.time() + self._breaker_cooldown_seconds
                    self._generation += 1
                    logger.warning(
                        "crypto breaker open for %ds after %d consecutive failures",
                        self._breaker_cooldown_seconds,
                        self._failure_count,
                    )
            return None

        with self._lock:
            self._failure_count = 0
        return result

    def reset_breaker(self) -> None:
        """Closes the breaker immediately rather than waiting for its own cooldown clock to
        expire and self-renew (see class docstring's _generation note, and validate()'s failure
        branch, which re-arms _open_until on every failed probe with no awareness of whether the
        service actually recovered) - for a caller that has *externally confirmed* the service is
        back (e.g. a TCP probe against its port) and wants the breaker to trust that immediately
        instead of on its own delayed schedule. Bumps _generation like a normal open/close cycle
        so every thread's cached connection is rebuilt fresh, matching a real recovery."""
        with self._lock:
            self._failure_count = 0
            self._open_until = 0.0
            self._generation += 1

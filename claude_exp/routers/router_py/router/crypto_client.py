import base64
import http.client
import json
import logging
import threading
import time

from shared.ssl_utils import build_client_context

logger = logging.getLogger(__name__)


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
    ):
        self._ssl_active = getattr(cfg, "ssl_active", False)
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

    def _new_connection(self) -> http.client.HTTPConnection:
        if self._ssl_active:
            return http.client.HTTPSConnection(self._host, self._port, context=self._ssl_context, timeout=5)
        return http.client.HTTPConnection(self._host, self._port, timeout=5)

    def _get_connection(self) -> http.client.HTTPConnection:
        conn = getattr(self._thread_local, "conn", None)
        if conn is None:
            conn = self._new_connection()
            self._thread_local.conn = conn
        return conn

    def _send(self, body: str, headers: dict) -> bytes:
        # A keep-alive connection idle between soak-test phases (or closed server-side after
        # crypto_host's own keep_alive_max_count) fails on first use, not gracefully - retry
        # once on a fresh connection rather than tripping the breaker on a stale socket alone.
        conn = self._get_connection()
        try:
            conn.request("POST", self._path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
        except (OSError, http.client.HTTPException):
            conn.close()
            self._thread_local.conn = None
            conn = self._get_connection()
            conn.request("POST", self._path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()

        if resp.status >= 400:
            raise http.client.HTTPException(f"HTTP {resp.status}: {data[:200]!r}")
        return data

    def validate(self, endpoint: str, pan: str, f47: str, router_stan: str = "") -> str:
        """Returns the enriched f47 on success, or "" on any failure (breaker open or HTTP
        error) - callers only overwrite their working f47 when this return value is truthy,
        so any failure path leaves the original f47 untouched. Handles the Fortanix
        PluginOutput envelope: response body is a base64-encoded JSON string, which we decode
        to reach the inner {"f47": ...} object.

        router_stan is passed through so crypto_host's own logs can be joined with this
        router's logs on the same transaction - it's not part of the Fortanix plugin contract,
        just an extra field crypto_host echoes into its log lines."""
        with self._lock:
            if time.time() < self._open_until:
                return ""

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
            logger.warning(
                "crypto_host %s call failed (router_stan=%s): %s",
                endpoint, router_stan, e, extra={"router_stan": router_stan},
            )
            with self._lock:
                self._failure_count += 1
                if self._failure_count >= self._breaker_threshold:
                    self._open_until = time.time() + self._breaker_cooldown_seconds
                    logger.warning(
                        "crypto breaker open for %ds after %d consecutive failures",
                        self._breaker_cooldown_seconds,
                        self._failure_count,
                    )
            return ""

        with self._lock:
            self._failure_count = 0
        return result

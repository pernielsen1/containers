import base64
import json
import logging
import threading
import time

import requests

logger = logging.getLogger(__name__)


class CryptoClient:
    """Fortanix-shaped crypto client: POST /sys/v1/plugins/{plugin_id}, bearer auth, base64
    response. Wired this way so swapping in a real Fortanix DSM tenant is a config/URL change,
    not a rewrite - matches CryptoClient.java / crypto_client.cpp."""

    def __init__(
        self,
        cfg,
        breaker_threshold: int = 5,
        breaker_cooldown_seconds: int = 30,
        pool_size: int = 20,
    ):
        self._base_url = f"http://{cfg.host}:{cfg.port}/sys/v1/plugins/{cfg.plugin_id}"
        self._bearer_token = cfg.bearer_token
        self._session = requests.Session()
        # Default HTTPAdapter pool_maxsize is 10 - both the 0100-leg worker pool and the
        # 0110-leg response-worker pool call validate() concurrently on this one shared
        # session, so at worker_threads=8/response_worker_threads=8 (the default) that's up
        # to 16 concurrent callers. A too-small pool doesn't fail requests, but every call
        # past pool_maxsize gets a fresh connection that's then discarded (not reused) once
        # returned - logged as "Connection pool is full, discarding connection" and, under
        # sustained load, the discarded sockets pile up in CLOSE_WAIT.
        adapter = requests.adapters.HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size)
        self._session.mount("http://", adapter)
        self._breaker_threshold = breaker_threshold
        self._breaker_cooldown_seconds = breaker_cooldown_seconds
        self._lock = threading.Lock()
        self._failure_count = 0
        self._open_until = 0.0

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
            resp = self._session.post(
                self._base_url,
                json={"operation": endpoint, "f2": pan, "f47": f47, "router_stan": router_stan},
                headers={"Authorization": f"Bearer {self._bearer_token}"},
                timeout=5,
            )
            resp.raise_for_status()
            decoded = base64.b64decode(resp.json()).decode("utf-8")
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

import logging
import threading
import time

import requests

logger = logging.getLogger(__name__)


class CryptoClient:
    def __init__(self, cfg, breaker_threshold: int = 5, breaker_cooldown_seconds: int = 30):
        self._base_url = f"http://{cfg.host}:{cfg.port}"
        self._session = requests.Session()
        self._breaker_threshold = breaker_threshold
        self._breaker_cooldown_seconds = breaker_cooldown_seconds
        self._lock = threading.Lock()
        self._failure_count = 0
        self._open_until = 0.0

    def validate(self, endpoint: str, pan: str, f47: str) -> str:
        """Returns the enriched f47 on success, or "" on any failure (breaker open or HTTP
        error) - callers only overwrite their working f47 when this return value is truthy,
        so any failure path leaves the original f47 untouched."""
        with self._lock:
            if time.time() < self._open_until:
                return ""

        try:
            resp = self._session.post(
                f"{self._base_url}/{endpoint}",
                json={"f2": pan, "f47": f47},
                timeout=5,
            )
            resp.raise_for_status()
            result = resp.json()["f47"]
        except Exception as e:
            logger.warning("crypto_host %s call failed: %s", endpoint, e)
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

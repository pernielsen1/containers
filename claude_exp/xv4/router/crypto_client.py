import logging
import threading
import time

import requests

logger = logging.getLogger(__name__)


class CryptoClient:
    def __init__(self, cfg, breaker_threshold=5, breaker_cooldown_seconds=30):
        self._base_url = f"http://{cfg.host}:{cfg.port}"
        self._session = requests.Session()
        self._threshold = breaker_threshold
        self._cooldown = breaker_cooldown_seconds
        self._lock = threading.Lock()
        self._failures = 0
        self._open_until = 0.0

    def validate(self, endpoint: str, pan: str, f47: str) -> str:
        with self._lock:
            now = time.monotonic()
            if self._open_until > now:
                logger.debug("crypto breaker open — skipping %s", endpoint)
                return f47

        try:
            resp = self._session.post(
                f"{self._base_url}/{endpoint}",
                json={"f2": pan, "f47": f47},
                timeout=5,
            )
            resp.raise_for_status()
            result = resp.json().get("f47", f47)
            with self._lock:
                self._failures = 0
            return result
        except Exception as e:
            logger.warning("crypto validate %s error: %s", endpoint, e)
            with self._lock:
                self._failures += 1
                if self._failures >= self._threshold:
                    self._open_until = time.monotonic() + self._cooldown
                    logger.error(
                        "crypto breaker opened after %d failures — cooldown %ds",
                        self._failures, self._cooldown,
                    )
                    self._failures = 0
            return f47

import threading
import time

import requests


class CryptoClient:
    def __init__(self, cfg, breaker_threshold: int = 5, breaker_cooldown_seconds: int = 30):
        self.base_url = f"http://{cfg.host}:{cfg.port}"
        self.session = requests.Session()
        self.breaker_threshold = breaker_threshold
        self.breaker_cooldown_seconds = breaker_cooldown_seconds

        self._lock = threading.Lock()
        self._failure_count = 0
        self._open_until = 0.0

    def validate(self, endpoint: str, pan: str, f47: str) -> str:
        with self._lock:
            if time.monotonic() < self._open_until:
                return ""

        try:
            resp = self.session.post(
                f"{self.base_url}/{endpoint}", json={"f2": pan, "f47": f47}, timeout=5
            )
            resp.raise_for_status()
            result = resp.json()["f47"]
        except (requests.RequestException, ValueError, KeyError):
            with self._lock:
                self._failure_count += 1
                if self._failure_count >= self.breaker_threshold:
                    self._open_until = time.monotonic() + self.breaker_cooldown_seconds
            return ""

        with self._lock:
            self._failure_count = 0
        return result

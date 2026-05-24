"""CryptoClient — HTTP client for crypto_host.

C++ equivalent: class wrapping libcurl or cpp-httplib.
One instance shared across worker threads; requests lib is thread-safe.
"""
from __future__ import annotations

import logging

import requests

from .config import CryptoConfig

log = logging.getLogger(__name__)


class CryptoClient:
    def __init__(self, cfg: CryptoConfig) -> None:
        self._base = f"http://{cfg.host}:{cfg.port}"
        self._session = requests.Session()

    def validate(self, endpoint: str, pan: str, f47: str) -> str:
        """Call /validate_0100 or /validate_0110.

        Returns enriched f47 string, or the original on any failure.
        C++ equivalent: blocking libcurl POST; same fallback behaviour.
        """
        url = f"{self._base}/{endpoint}"
        try:
            r = self._session.post(url, json={"f2": pan, "f47": f47}, timeout=5)
            r.raise_for_status()
            return r.json().get("f47", f47)
        except Exception as e:
            log.warning("crypto %s failed: %s", endpoint, e)
            return f47

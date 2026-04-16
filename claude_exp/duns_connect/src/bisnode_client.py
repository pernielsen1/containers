"""
bisnode_client.py

Bisnode Credit Data API client.  Handles OAuth2 authentication and
company searches by DUNS number or registration number.
"""

import os
import requests

SUPPORTED_COUNTRIES = ["SE", "FI", "DK", "NO"]


class BisnodeClient:

    def __init__(self, env_config: dict):
        self._client_id = os.environ['DUNS_CLIENT_ID']
        self._client_secret = os.environ['DUNS_CLIENT_SECRET']
        self._token_url = env_config.get("TokenUrl", "https://login.bisnode.com/as/token.oauth2")
        self._search_endpoint = f"{env_config['ApiBaseUrl']}/companies"
        self._access_token: str | None = None
        self._proxies = self._parse_proxies(env_config)

    def _parse_proxies(self, env_config: dict) -> dict | None:
        proxy_source = env_config.get("Proxies") or env_config.get("proxies") or env_config.get("Proxy")
        if proxy_source is None:
            proxy_source = self._get_proxies_from_env()
        if isinstance(proxy_source, str):
            return {"http": proxy_source, "https": proxy_source}
        if isinstance(proxy_source, dict):
            return proxy_source
        return None

    def _get_proxies_from_env(self) -> dict | None:
        http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if not http_proxy and not https_proxy:
            return None

        proxies: dict[str, str] = {}
        if http_proxy:
            proxies["http"] = http_proxy
        if https_proxy:
            proxies["https"] = https_proxy
        return proxies

    @property
    def proxies(self) -> dict | None:
        return self._proxies

    def authenticate(self) -> None:
        """Fetch and store an OAuth2 access token (client credentials flow)."""
        response = requests.post(
            self._token_url,
            data={
                "grant_type": "client_credentials",
                "scope": "credit_data_companies",
            },
            auth=(self._client_id, self._client_secret),
            timeout=30,
            proxies=self._proxies,
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise ValueError(f"No access_token in response: {response.text}")
        self._access_token = token

    def search_by_duns(self, duns_number: str) -> dict | None:
        """Try each supported country in turn; return first response with hits."""
        for country in SUPPORTED_COUNTRIES:
            data = self._post({"dunsNumber": duns_number, "country": country})
            if data is not None:
                return data
        return None

    def search_by_registration_number(self, registration_number: str, country: str) -> dict | None:
        """Search by registration number. Uses the supplied country directly if valid,
        otherwise falls back to trying all supported countries."""
        countries = (
            [country.upper()]
            if country and country.upper() in SUPPORTED_COUNTRIES
            else SUPPORTED_COUNTRIES
        )
        for c in countries:
            data = self._post({"registrationNumber": registration_number, "country": c})
            if data is not None:
                return data
        return None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _post(self, payload: dict) -> dict | None:
        """POST to the search endpoint; return data if hits present, else None."""
        response = requests.post(
            self._search_endpoint,
            json=payload,
            headers=self._auth_headers(),
            timeout=30,
            proxies=self._proxies,
        )
        if response.status_code == 400:
            return None
        response.raise_for_status()
        data = response.json()
        hits = data.get("companies") or data.get("hits") or data.get("results") or []
        return data if hits else None

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

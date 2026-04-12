"""
fetch_duns_info.py

Reads DUNS numbers from duns_to_collect.csv and fetches company information
from the Bisnode Credit Data API for each entry. Results are written to
output/<DUNS_NO>_<timestamp>.txt.

If DUNS_NO is -1, the search falls back to registrationNumber + CNTRY_CD.

Usage:
    python fetch_duns_info.py [sandbox|production]

The environment defaults to the value of "default_environment" in config.json
(which defaults to "sandbox" if not set).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd
import requests

from duns_cache import DunsCache

CONFIG_FILE = "config.json"
CSV_FILE = "duns_to_collect.csv"
OUTPUT_DIR = "output"

# The API requires a country. Used as fallback when CNTRY_CD is absent.
SUPPORTED_COUNTRIES = ["SE", "FI", "DK", "NO"]


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def get_access_token(client_id: str, client_secret: str, token_url: str) -> str:
    """Obtain an OAuth2 access token using the client credentials flow."""
    response = requests.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "scope": "credit_data_companies",
        },
        auth=(client_id, client_secret),
        timeout=30,
    )
    response.raise_for_status()
    token_data = response.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise ValueError(f"No access_token in response: {token_data}")
    return access_token


def _post_search(endpoint: str, payload: dict, headers: dict) -> dict | None:
    """POST to the search endpoint and return data if hits found, else None."""
    response = requests.post(endpoint, json=payload, headers=headers, timeout=30)
    if response.status_code == 400:
        return None
    response.raise_for_status()
    data = response.json()
    hits = data.get("companies") or data.get("hits") or data.get("results") or []
    return data if hits else None


def search_by_duns(duns_number: str, access_token: str, search_endpoint: str) -> dict | None:
    """
    Search for a company by DUNS number. Tries each supported country in turn
    and returns the first response that contains results, or None if not found.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    for country in SUPPORTED_COUNTRIES:
        data = _post_search(
            search_endpoint,
            {"dunsNumber": duns_number, "country": country},
            headers,
        )
        if data is not None:
            return data
    return None


def search_by_registration_number(
    registration_number: str,
    country: str,
    access_token: str,
    search_endpoint: str,
) -> dict | None:
    """
    Search for a company by registration number and country.
    If country is unknown, tries all supported countries in turn.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    countries = [country.upper()] if country and country.upper() in SUPPORTED_COUNTRIES else SUPPORTED_COUNTRIES
    for c in countries:
        data = _post_search(
            search_endpoint,
            {"registrationNumber": registration_number, "country": c},
            headers,
        )
        if data is not None:
            return data
    return None


def read_duns_csv(path: str) -> pd.DataFrame:
    """Load the semicolon-delimited CSV with pandas."""
    return pd.read_csv(path, sep=";", dtype=str).fillna("")


def write_output(identifier: str, data: dict | None) -> str:
    """Write the result JSON to output/<identifier>_<timestamp>.txt."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(OUTPUT_DIR, f"{identifier}_{timestamp}.txt")
    with open(filename, "w", encoding="utf-8") as fh:
        if data is not None:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        else:
            fh.write(f"No results found for: {identifier}\n")
    return filename


def main() -> None:
    # --- Parse command-line arguments ---
    parser = argparse.ArgumentParser(
        description="Fetch company information from Bisnode Credit Data API by DUNS number."
    )
    parser.add_argument(
        "environment",
        nargs="?",
        choices=["sandbox", "production"],
        default=None,
        help="Target environment: 'sandbox' or 'production' (default: value of default_environment in config.json)",
    )
    args = parser.parse_args()

    # --- Load config ---
    try:
        config = load_config(CONFIG_FILE)
    except FileNotFoundError:
        sys.exit(f"ERROR: Config file not found: {CONFIG_FILE}")

    # Resolve environment: CLI arg > config default > hardcoded fallback
    environment = args.environment or config.get("default_environment", "sandbox")
    if environment not in ("sandbox", "production"):
        sys.exit(f"ERROR: Unknown environment '{environment}'. Must be 'sandbox' or 'production'.")

    env_config = config.get(environment)
    if not env_config:
        sys.exit(f"ERROR: No configuration block found for environment '{environment}' in config.json")

    client_id = env_config.get("ClientId")
    client_secret = env_config.get("ClientSecret")
    token_url = env_config.get("TokenUrl", "https://login.bisnode.com/as/token.oauth2")
    api_base_url = env_config.get("ApiBaseUrl")

    if not client_id or not client_secret:
        sys.exit(f"ERROR: ClientId and/or ClientSecret missing for environment '{environment}' in config.json")
    if not api_base_url:
        sys.exit(f"ERROR: ApiBaseUrl missing for environment '{environment}' in config.json")

    search_endpoint = f"{api_base_url}/companies"

    cache = DunsCache(
        cache_dir=config.get("cache_dir", "cache"),
        age_in_days=config.get("age_in_days", 30),
    )

    print(f"Environment: {environment}")
    print(f"API base URL: {api_base_url}")
    print(f"Cache dir: {cache.cache_dir}  (max age: {cache.age_in_days} days)")

    # --- Read DUNS numbers ---
    try:
        df = read_duns_csv(CSV_FILE)
    except FileNotFoundError:
        sys.exit(f"ERROR: CSV file not found: {CSV_FILE}")

    if df.empty:
        print("No records found in CSV — nothing to do.")
        return

    print(f"Loaded {len(df)} record(s) from {CSV_FILE}")

    # --- Obtain access token once, reuse for all requests ---
    print("Obtaining access token...")
    try:
        access_token = get_access_token(client_id, client_secret, token_url)
    except requests.HTTPError as exc:
        sys.exit(f"ERROR: Failed to obtain access token: {exc}")
    print("Access token obtained.")

    # --- Process each row ---
    for _, row in df.iterrows():
        duns_number = row.get("DUNS_NO", "").strip()
        country = row.get("CNTRY_CD", "").strip()
        registration_number = row.get("registrationNumber", "").strip()
        name = row.get("NAME", "").strip()

        if duns_number == "-1":
            if not registration_number:
                print(f"  WARNING: DUNS_NO is -1 but registrationNumber is empty — skipping ({name})")
                continue
            print(f"\nSearching by registrationNumber: {registration_number}  country: {country}  ({name})")

            # Cache cannot be checked without a known DUNS_NO — go straight to API
            try:
                data = search_by_registration_number(
                    registration_number, country, access_token, search_endpoint
                )
            except requests.HTTPError as exc:
                print(f"  ERROR: API request failed for {registration_number}: {exc}")
                data = {"error": str(exc), "registrationNumber": registration_number}

            # Use the returned dunsNumber as the output file identifier if available
            hits = (data or {}).get("companies") or (data or {}).get("hits") or (data or {}).get("results") or []
            duns_from_response = hits[0].get("dunsNumber") if hits else None
            identifier = duns_from_response or registration_number
            if duns_from_response:
                print(f"  -> Resolved dunsNumber: {duns_from_response}")

        else:
            if not duns_number:
                print("  WARNING: Skipping row with empty DUNS_NO")
                continue
            identifier = duns_number
            print(f"\nSearching DUNS: {duns_number}  ({name})")

            # Check cache first
            cached = cache.get_data(row)
            if cached is not None:
                output_path = write_output(identifier, cached)
                print(f"  -> Served from cache: {output_path}")
                continue

            try:
                data = search_by_duns(duns_number, access_token, search_endpoint)
            except requests.HTTPError as exc:
                print(f"  ERROR: API request failed for {duns_number}: {exc}")
                data = {"error": str(exc), "duns_number": duns_number}

        # Save successful API responses to cache (keyed by resolved DUNS_NO)
        if data is not None and "error" not in data:
            cache.save(identifier, data)

        output_path = write_output(identifier, data)

        if data is not None and "error" not in data:
            print(f"  -> Result written to: {output_path}")
        elif data is not None and "error" in data:
            print(f"  -> Error details written to: {output_path}")
        else:
            print(f"  -> No results found; placeholder written to: {output_path}")

    print("\nDone.")


if __name__ == "__main__":
    main()

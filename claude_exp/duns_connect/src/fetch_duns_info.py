"""
fetch_duns_info.py

Orchestrates company data retrieval:
  1. Reads duns_to_collect.csv
  2. For each row, checks the cache before hitting the API
  3. Writes results to output/<identifier>_<timestamp>.txt

If DUNS_NO is -1, the search uses registrationNumber + CNTRY_CD instead.
The returned dunsNumber is then used as the output file identifier.

Usage:
    python fetch_duns_info.py [sandbox|production]
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd
import requests

from bisnode_client import BisnodeClient
from duns_cache import DunsCache

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
CSV_FILE = "input/duns_to_collect.csv"
OUTPUT_DIR = "output"


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path, sep=";", dtype=str).fillna("")


def write_output(identifier: str, data: dict | None) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(OUTPUT_DIR, f"{identifier}_{timestamp}.txt")
    with open(path, "w", encoding="utf-8") as fh:
        if data is not None:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        else:
            fh.write(f"No results found for: {identifier}\n")
    return path


def resolve_hits(data: dict | None) -> list:
    if not data:
        return []
    return data.get("companies") or data.get("hits") or data.get("results") or []


def process_row(row, client: BisnodeClient, cache: DunsCache) -> tuple[str, dict | None]:
    """
    Determine the search strategy for the row, check cache, call API if needed.
    Returns (identifier, data).
    """
    duns_number = row.get("DUNS_NO", "").strip()
    country = row.get("CNTRY_CD", "").strip()
    registration_number = row.get("registrationNumber", "").strip()
    name = row.get("NAME", "").strip()

    if duns_number == "-1":
        if not registration_number:
            print(f"  WARNING: DUNS_NO is -1 but registrationNumber is empty — skipping ({name})")
            return "", None

        print(f"\nSearching by registrationNumber: {registration_number}  country: {country}  ({name})")

        if cache.is_no_hit(registration_number):
            return registration_number, None

        data = client.search_by_registration_number(registration_number, country)

        hits = resolve_hits(data)
        duns_from_response = hits[0].get("dunsNumber") if hits else None
        identifier = duns_from_response or registration_number
        if duns_from_response:
            print(f"  -> Resolved dunsNumber: {duns_from_response}")
        return identifier, data

    else:
        if not duns_number:
            print("  WARNING: Skipping row with empty DUNS_NO")
            return "", None

        print(f"\nSearching DUNS: {duns_number}  ({name})")

        if cache.is_no_hit(duns_number):
            return duns_number, None

        cached = cache.get_data(row)
        if cached is not None:
            return duns_number, cached

        data = client.search_by_duns(duns_number)
        return duns_number, data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch company information from the Bisnode Credit Data API."
    )
    parser.add_argument(
        "environment",
        nargs="?",
        choices=["sandbox", "production"],
        default=None,
        help="Target environment (default: default_environment in config.json)",
    )
    args = parser.parse_args()

    try:
        config = load_config(CONFIG_FILE)
    except FileNotFoundError:
        sys.exit(f"ERROR: Config file not found: {CONFIG_FILE}")

    environment = args.environment or config.get("default_environment", "sandbox")
    env_config = config.get(environment)
    if not env_config:
        sys.exit(f"ERROR: No config block for environment '{environment}'")
    if not env_config.get("ClientId") or not env_config.get("ClientSecret"):
        sys.exit(f"ERROR: ClientId/ClientSecret missing for environment '{environment}'")

    client = BisnodeClient(env_config)
    cache = DunsCache(
        cache_dir=config.get("cache_dir", "cache"),
        age_in_days=config.get("age_in_days", 30),
        no_hit_age_in_days=config.get("no_hit_age_in_days", 15),
    )

    print(f"Environment : {environment}")
    print(f"API base URL: {env_config['ApiBaseUrl']}")
    if env_config.get("Proxies") or env_config.get("proxies") or env_config.get("Proxy"):
        print("Proxy       : configured")
    print(f"Cache dir   : {cache.cache_dir}  (max age: {cache.age_in_days} days)")

    try:
        df = read_csv(CSV_FILE)
    except FileNotFoundError:
        sys.exit(f"ERROR: CSV file not found: {CSV_FILE}")

    if df.empty:
        print("No records found in CSV — nothing to do.")
        return

    print(f"Loaded {len(df)} record(s) from {CSV_FILE}")

    print("Obtaining access token...")
    try:
        client.authenticate()
    except requests.HTTPError as exc:
        sys.exit(f"ERROR: Authentication failed: {exc}")
    print("Access token obtained.")

    for _, row in df.iterrows():
        try:
            identifier, data = process_row(row, client, cache)
        except requests.HTTPError as exc:
            key = row.get("DUNS_NO", "").strip() or row.get("registrationNumber", "").strip()
            print(f"  ERROR: API request failed for {key}: {exc}")
            data = {"error": str(exc)}
            identifier = key

        if not identifier:
            continue

        # Cache successful API responses (skip if data came from cache already)
        if data is not None and "error" not in data and not cache.get_data(row):
            cache.save(identifier, data)

        # Record no-hits so we don't keep retrying lost causes
        if data is None and not cache.is_no_hit(identifier):
            no_hit_path = cache.save_no_hit(identifier)
            print(f"  -> No-hit recorded: {no_hit_path}")

        output_path = write_output(identifier, data)

        if data is None:
            print(f"  -> No results found; placeholder written to: {output_path}")
        elif "error" in data:
            print(f"  -> Error details written to: {output_path}")
        else:
            print(f"  -> Result written to: {output_path}")

    print("\nDone.")


if __name__ == "__main__":
    main()

"""
duns_cache.py

Cache layer for Bisnode API responses. Files are stored as:
    <cache_dir>/<DUNS_NO>_<YYYYMMDD>_<HHMMSS>.txt

get_data(row) returns cached data when a file for the row's DUNS_NO exists
and is within the allowed age; otherwise returns None so the caller knows
to fetch from the API.

No-hit entries (identifiers that returned zero results) are stored under:
    <cache_dir>/no_hits/<identifier>_<YYYYMMDD>_<HHMMSS>.txt

is_no_hit(identifier) returns True when a fresh no-hit entry exists, so the
caller can skip the API call entirely for known "lost causes".
"""

import json
import os
from datetime import datetime, timezone


CACHE_DIR = "cache"


class DunsCache:
    def __init__(self, cache_dir: str, age_in_days: int, no_hit_age_in_days: int = 15):
        self.cache_dir = cache_dir
        self.age_in_days = age_in_days
        self.no_hit_age_in_days = no_hit_age_in_days
        self._no_hit_dir = os.path.join(cache_dir, "no_hits")

    def get_data(self, row) -> dict | None:
        """
        Return cached data for the row if a fresh cache file exists, else None.
        Rows with DUNS_NO == -1 cannot be looked up by DUNS and always return None.
        The row's age_in_days column, when filled, overrides the global setting.
        """
        duns_number = str(row.get("DUNS_NO", "")).strip()
        if not duns_number or duns_number == "-1":
            return None

        row_age = str(row.get("age_in_days", "")).strip()
        age_in_days = int(row_age) if row_age.isdigit() else self.age_in_days

        cache_file = self._find_latest(duns_number)
        if cache_file is None:
            return None

        if not self._is_fresh(cache_file, age_in_days):
            print(f"  [cache] Stale entry for {duns_number} (max age: {age_in_days}d) — will re-fetch")
            return None

        print(f"  [cache] Hit for {duns_number}: {cache_file}")
        with open(cache_file, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def is_no_hit(self, identifier: str) -> bool:
        """Return True if a fresh no-hit entry exists for identifier."""
        cache_file = self._find_latest_no_hit(identifier)
        if cache_file is None:
            return False
        if not self._is_fresh(cache_file, self.no_hit_age_in_days):
            print(f"  [cache/no_hits] Stale entry for {identifier} (max age: {self.no_hit_age_in_days}d) — will retry")
            return False
        print(f"  [cache/no_hits] Known no-hit for {identifier} — skipping API call")
        return True

    def save_no_hit(self, identifier: str) -> str:
        """Record that identifier produced no results; return the file path."""
        os.makedirs(self._no_hit_dir, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self._no_hit_dir, f"{identifier}_{timestamp}.txt")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"identifier": identifier, "cached_at": timestamp}, fh)
        return path

    def save(self, duns_number: str, data: dict) -> str:
        """Write data to the cache and return the file path."""
        os.makedirs(self.cache_dir, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.cache_dir, f"{duns_number}_{timestamp}.txt")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        return path

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _find_latest_no_hit(self, identifier: str) -> str | None:
        """Return the most recent no-hit cache file for identifier, or None."""
        if not os.path.isdir(self._no_hit_dir):
            return None
        prefix = f"{identifier}_"
        matches = [
            f for f in os.listdir(self._no_hit_dir)
            if f.startswith(prefix) and f.endswith(".txt")
        ]
        if not matches:
            return None
        matches.sort(reverse=True)
        return os.path.join(self._no_hit_dir, matches[0])

    def _find_latest(self, duns_number: str) -> str | None:
        """Return the most recent cache file for duns_number, or None."""
        if not os.path.isdir(self.cache_dir):
            return None
        prefix = f"{duns_number}_"
        matches = [
            f for f in os.listdir(self.cache_dir)
            if f.startswith(prefix) and f.endswith(".txt")
        ]
        if not matches:
            return None
        matches.sort(reverse=True)  # lexicographic sort on YYYYMMDD_HHMMSS
        return os.path.join(self.cache_dir, matches[0])

    def _is_fresh(self, filepath: str, age_in_days: int) -> bool:
        """Return True if the cache file is within age_in_days."""
        stem = os.path.basename(filepath)[:-4]  # strip .txt
        parts = stem.rsplit("_", 2)              # [duns, YYYYMMDD, HHMMSS]
        if len(parts) < 3:
            return False
        try:
            file_time = datetime.strptime(
                f"{parts[-2]}_{parts[-1]}", "%Y%m%d_%H%M%S"
            ).replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - file_time
            return age.days <= age_in_days
        except ValueError:
            return False

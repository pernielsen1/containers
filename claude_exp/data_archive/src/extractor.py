import csv
import json
from pathlib import Path

from .archiver import decompress_from_base64

DEFAULT_CSV = Path(__file__).parent.parent / 'output' / 'pass1' / 'archive.csv'


class Extractor:
    def __init__(self, csv_path: Path = DEFAULT_CSV):
        self._csv_path = csv_path

    def _matching_rows(self, key: str, type_: str) -> list[dict]:
        with open(self._csv_path, encoding='utf-8-sig', newline='') as f:
            return [r for r in csv.DictReader(f, delimiter=';')
                    if r['key'] == key and r['type'] == type_]

    def extract_latest(self, key: str, type_: str) -> tuple[str, str]:
        """Return (suffix, json_str) for the lexicographically latest suffix."""
        rows = self._matching_rows(key, type_)
        if not rows:
            raise KeyError(f"No entry found for key='{key}' type='{type_}'")
        row = max(rows, key=lambda r: r['suffix'])
        return row['suffix'], decompress_from_base64(row['base64_json'])

    def extract_all(self, key: str, type_: str) -> list[tuple[str, str]]:
        """Return list of (suffix, json_str) for all matching entries."""
        rows = self._matching_rows(key, type_)
        if not rows:
            raise KeyError(f"No entry found for key='{key}' type='{type_}'")
        return [(r['suffix'], decompress_from_base64(r['base64_json'])) for r in rows]

    def extract(self, key: str, type_: str) -> str:
        """Return the JSON string for the latest version (backwards-compatible)."""
        _, json_str = self.extract_latest(key, type_)
        return json_str

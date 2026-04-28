#!/usr/bin/env python3
"""Extract a JSON record by key and type from the archive CSV."""

import csv
import gzip
import base64
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
DEFAULT_CSV = BASE_DIR / 'output' / 'archive.csv'
EXTRACT_DIR = BASE_DIR / 'extract'


class Extractor:
    def __init__(self, csv_path: Path = DEFAULT_CSV):
        self._csv_path = csv_path

    def extract(self, key: str, type_: str) -> str:
        """Return the JSON string for the first matching (key, type) entry."""
        with open(self._csv_path, encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f, delimiter=';'):
                if row['key'] == key and row['type'] == type_:
                    compressed = base64.b64decode(row['base64_json'])
                    return gzip.decompress(compressed).decode('utf-8')
        raise KeyError(f"No entry found for key='{key}' type='{type_}'")


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Usage: python3 extract.py <key> <type> [csv_path]', file=sys.stderr)
        sys.exit(1)

    key = sys.argv[1]
    type_ = sys.argv[2]
    csv_path = Path(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_CSV

    json_str = Extractor(csv_path).extract(key, type_)

    EXTRACT_DIR.mkdir(exist_ok=True)
    out_file = EXTRACT_DIR / f'{key}_{type_}.json'
    out_file.write_text(json.dumps(json.loads(json_str), indent=2), encoding='utf-8')
    print(f'Written to {out_file}')

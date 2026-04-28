import csv
import json
from pathlib import Path

from .archiver import decompress_from_base64

DEFAULT_CSV = Path(__file__).parent.parent / 'output' / 'archive.csv'


class Extractor:
    def __init__(self, csv_path: Path = DEFAULT_CSV):
        self._csv_path = csv_path

    def extract(self, key: str, type_: str) -> str:
        """Return the JSON string for the first matching (key, type) entry."""
        with open(self._csv_path, encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                if row['key'] == key and row['type'] == type_:
                    return decompress_from_base64(row['base64_json'])
        raise KeyError(f"No entry found for key='{key}' type='{type_}'")


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 3:
        print('Usage: python3 -m src.extractor <key> <type> [csv_path]', file=sys.stderr)
        sys.exit(1)

    key = sys.argv[1]
    type_ = sys.argv[2]
    csv_path = Path(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_CSV

    result = Extractor(csv_path).extract(key, type_)
    print(json.dumps(json.loads(result), indent=2))

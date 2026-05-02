#!/usr/bin/env python3
"""Extract a JSON record by key and type from the archive CSV."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src.extractor import Extractor, DEFAULT_CSV

EXTRACT_DIR = Path(__file__).parent / 'extract'


def _out_name(key: str, type_: str, suffix: str) -> str:
    return f'{key}_{type_}_{suffix}.json' if suffix else f'{key}_{type_}.json'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Extract records from archive CSV.')
    parser.add_argument('key')
    parser.add_argument('type')
    parser.add_argument('--version', choices=['latest', 'all'], default='latest')
    parser.add_argument('--csv', type=Path, default=DEFAULT_CSV)
    args = parser.parse_args()

    ex = Extractor(args.csv)
    EXTRACT_DIR.mkdir(exist_ok=True)

    if args.version == 'latest':
        suffix, json_str = ex.extract_latest(args.key, args.type)
        out = EXTRACT_DIR / _out_name(args.key, args.type, suffix)
        out.write_text(json.dumps(json.loads(json_str), indent=2), encoding='utf-8')
        print(f'Written to {out}')
    else:
        entries = ex.extract_all(args.key, args.type)
        for suffix, json_str in entries:
            out = EXTRACT_DIR / _out_name(args.key, args.type, suffix)
            out.write_text(json.dumps(json.loads(json_str), indent=2), encoding='utf-8')
            print(f'Written to {out}')

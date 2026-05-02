#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src.field_extractor import extract_fields, DEFAULT_RULES

BASE_DIR = Path(__file__).parent

if __name__ == '__main__':
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR
    archive_csv = base / 'output' / 'pass1' / 'archive.csv'
    rules_csv   = base / DEFAULT_RULES.relative_to(BASE_DIR)
    output_csv  = base / 'output' / 'pass2' / 'extracted.csv'
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    n = extract_fields(archive_csv=archive_csv, rules_csv=rules_csv, output_csv=output_csv)
    print(f'Done: {n} rows written to {output_csv}')

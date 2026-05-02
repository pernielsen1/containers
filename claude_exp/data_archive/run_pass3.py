#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src.merger import Merger

BASE_DIR = Path(__file__).parent

if __name__ == '__main__':
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR
    pass2_csv = base / 'output' / 'pass2' / 'extracted.csv'
    full_extract_csv = base / 'full_extract.csv'
    n = Merger().merge(pass2_csv=pass2_csv, full_extract_csv=full_extract_csv)
    print(f'Done: {n} rows appended to {full_extract_csv}')

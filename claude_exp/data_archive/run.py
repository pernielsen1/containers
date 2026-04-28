#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src.processor import process_input, BASE_DIR

if __name__ == '__main__':
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR
    result = process_input(base)
    print(f"Done: {result['committed']} committed, {result['error']} errors, {result['skipped']} skipped")

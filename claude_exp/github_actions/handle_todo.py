"""
handle_todo.py — processes ASCII text files from the todo/ directory.
For each file:
  - reads content and converts all letters to uppercase
  - writes a copy to next_step/ with a unique filename:
    <basename>_CCYYMMDD.HH-MM-SS.<extension>
"""

import os
import sys
from datetime import datetime
from pathlib import Path


def unique_filename(filepath: Path) -> str:
    ts = datetime.now().strftime("%Y%m%d.%H-%M-%S")
    return f"{filepath.stem}_{ts}{filepath.suffix}"


def process_file(filepath: Path, next_step_dir: Path) -> None:
    content = filepath.read_text(encoding="ascii", errors="replace")
    uppercased = content.upper()

    dest = next_step_dir / unique_filename(filepath)
    dest.write_text(uppercased, encoding="ascii")
    print(f"  {filepath} -> {dest}")


def main(files: list[str]) -> None:
    next_step_dir = Path("next_step")
    next_step_dir.mkdir(exist_ok=True)

    if not files:
        print("No files provided.")
        return

    for f in files:
        p = Path(f)
        if p.is_file():
            process_file(p, next_step_dir)
        else:
            print(f"  Skipped (not a file): {f}")


if __name__ == "__main__":
    main(sys.argv[1:])

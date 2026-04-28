#!/usr/bin/env python3
"""Copy archive.csv to backups/archive_CCYYMMDD_HHMMSS.csv."""

import shutil
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
SRC = BASE_DIR / 'output' / 'archive.csv'
BACKUP_DIR = BASE_DIR / 'backups'


def backup() -> Path:
    if not SRC.exists():
        raise FileNotFoundError(f"Archive not found: {SRC}")
    BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    dest = BACKUP_DIR / f'archive_{timestamp}.csv'
    shutil.copy2(SRC, dest)
    return dest


if __name__ == '__main__':
    out = backup()
    print(f'Backup written to {out}')

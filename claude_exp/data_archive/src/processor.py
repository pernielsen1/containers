import uuid
import shutil
from datetime import datetime
from pathlib import Path

import filelock

from .parser import parse_filename
from .validator import validate_json
from .archiver import compress_to_base64, ensure_csv_intact, write_header_if_needed, append_to_csv

BASE_DIR = Path(__file__).parent.parent


def _move_to_error(src: Path, error_dir: Path) -> Path:
    dest = error_dir / src.name
    if dest.exists():
        dest = error_dir / f'{src.stem}_{uuid.uuid4().hex[:8]}{src.suffix}'
    shutil.move(str(src), dest)
    return dest


def _move_to_committed(src: Path, committed_dir: Path) -> Path:
    dest = committed_dir / src.name
    shutil.move(str(src), dest)
    return dest


def process_input(base_dir: Path = BASE_DIR) -> dict:
    output_csv = base_dir / 'output' / 'pass1' / 'archive.csv'
    lock_path = base_dir / 'output' / 'pass1' / 'archive.csv.lock'
    input_dir = base_dir / 'input'
    committed_dir = base_dir / 'committed'
    error_dir = base_dir / 'error'

    for d in [input_dir, committed_dir, error_dir, output_csv.parent]:
        d.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    stats = {'committed': 0, 'error': 0, 'skipped': 0}

    with filelock.FileLock(str(lock_path)):
        ensure_csv_intact(output_csv)
        write_header_if_needed(output_csv)

        for json_file in sorted(input_dir.glob('*.json')):
            try:
                key, type_, suffix = parse_filename(json_file.name)
            except ValueError:
                _move_to_error(json_file, error_dir)
                stats['error'] += 1
                continue

            try:
                content = json_file.read_text(encoding='utf-8')
            except OSError:
                stats['skipped'] += 1
                continue

            if not validate_json(content):
                _move_to_error(json_file, error_dir)
                stats['error'] += 1
                continue

            b64 = compress_to_base64(content)
            append_to_csv(output_csv, run_id, key, type_, suffix, b64)
            _move_to_committed(json_file, committed_dir)
            stats['committed'] += 1

    return stats

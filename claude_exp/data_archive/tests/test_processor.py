import json
import gzip
import base64
from pathlib import Path

import pytest

from src.processor import process_input
from src.archiver import decompress_from_base64

HEADER = 'key;type;base64_json'


def make_input(base: Path, name: str, content: str) -> Path:
    d = base / 'input'
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text(content, encoding='utf-8')
    return f


def csv_data_lines(base: Path) -> list[str]:
    csv = base / 'output' / 'archive.csv'
    lines = csv.read_text(encoding='utf-8-sig').splitlines()
    assert lines[0] == HEADER
    return lines[1:]


# --- basic flow ---

def test_valid_file_committed(tmp_path):
    make_input(tmp_path, 'account_loan_001.json', '{"amount": 100}')
    stats = process_input(tmp_path)
    assert stats == {'committed': 1, 'error': 0, 'skipped': 0}
    assert (tmp_path / 'committed' / 'account_loan_001.json').exists()
    assert not (tmp_path / 'input' / 'account_loan_001.json').exists()


def test_valid_file_csv_entry(tmp_path):
    payload = '{"amount": 100}'
    make_input(tmp_path, 'account_loan_001.json', payload)
    process_input(tmp_path)
    lines = csv_data_lines(tmp_path)
    assert len(lines) == 1
    key, type_, b64 = lines[0].split(';')
    assert key == 'account'
    assert type_ == 'loan'
    assert decompress_from_base64(b64) == payload


def test_invalid_json_goes_to_error(tmp_path):
    make_input(tmp_path, 'account_loan_002.json', 'not valid json{')
    stats = process_input(tmp_path)
    assert stats['error'] == 1
    assert stats['committed'] == 0
    assert (tmp_path / 'error' / 'account_loan_002.json').exists()


def test_bad_filename_goes_to_error(tmp_path):
    make_input(tmp_path, 'badname.json', '{"x": 1}')
    stats = process_input(tmp_path)
    assert stats['error'] == 1
    assert (tmp_path / 'error' / 'badname.json').exists()


def test_error_naming_conflict_gets_unique_suffix(tmp_path):
    (tmp_path / 'error').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'error' / 'account_loan_003.json').write_text('existing')
    make_input(tmp_path, 'account_loan_003.json', 'bad json{')
    process_input(tmp_path)
    error_files = list((tmp_path / 'error').glob('account_loan_003*.json'))
    assert len(error_files) == 2


# --- multiple files ---

def test_multiple_files_all_processed(tmp_path):
    for i in range(10):
        make_input(tmp_path, f'key{i}_type{i}_{i:04d}.json', f'{{"i": {i}}}')
    stats = process_input(tmp_path)
    assert stats['committed'] == 10
    lines = csv_data_lines(tmp_path)
    assert len(lines) == 10


def test_mixed_valid_and_invalid(tmp_path):
    make_input(tmp_path, 'a_b_001.json', '{"ok": true}')
    make_input(tmp_path, 'c_d_002.json', 'bad{')
    make_input(tmp_path, 'e_f_003.json', '{"ok": true}')
    stats = process_input(tmp_path)
    assert stats['committed'] == 2
    assert stats['error'] == 1
    lines = csv_data_lines(tmp_path)
    assert len(lines) == 2


# --- idempotency / incremental runs ---

def test_second_run_appends_new_entries(tmp_path):
    make_input(tmp_path, 'a_b_001.json', '{"x": 1}')
    process_input(tmp_path)
    make_input(tmp_path, 'a_b_002.json', '{"x": 2}')
    process_input(tmp_path)
    lines = csv_data_lines(tmp_path)
    assert len(lines) == 2


def test_second_run_does_not_reprocess_committed(tmp_path):
    make_input(tmp_path, 'a_b_001.json', '{"x": 1}')
    process_input(tmp_path)
    stats = process_input(tmp_path)  # input/ is now empty
    assert stats['committed'] == 0
    lines = csv_data_lines(tmp_path)
    assert len(lines) == 1  # first run's entry preserved


# --- resilience: crash recovery ---

def test_partial_line_recovered_on_next_run(tmp_path):
    make_input(tmp_path, 'a_b_001.json', '{"x": 1}')
    process_input(tmp_path)

    # Simulate crash: append partial line to CSV
    csv = tmp_path / 'output' / 'archive.csv'
    with open(csv, 'ab') as f:
        f.write(b'incomplete;entry;NO_NEWLINE')

    # Next run: ensure_csv_intact should truncate the partial line
    make_input(tmp_path, 'a_b_002.json', '{"x": 2}')
    process_input(tmp_path)

    lines = csv_data_lines(tmp_path)
    assert len(lines) == 2  # original entry + new one, partial line gone
    assert all(';' in line for line in lines)


def test_all_lines_end_with_newline(tmp_path):
    for i in range(20):
        make_input(tmp_path, f'k_t_{i:04d}.json', f'{{"n": {i}}}')
    process_input(tmp_path)
    csv = tmp_path / 'output' / 'archive.csv'
    raw = csv.read_bytes()
    assert raw.endswith(b'\n'), "CSV must end with newline"
    # Every line must be complete
    for line in raw.split(b'\n')[:-1]:  # last split produces empty string
        assert len(line) > 0


# --- large file simulation ---

def test_large_volume_csv_integrity(tmp_path):
    """Simulate a 'large' resulting CSV by processing many files.
    Verifies line count, completeness, and round-trip correctness on a sample."""
    n = 1000
    payloads = {}
    for i in range(n):
        name = f'entity_record_{i:05d}.json'
        payload = json.dumps({"index": i, "data": "x" * 50})
        payloads[name] = payload
        make_input(tmp_path, name, payload)

    stats = process_input(tmp_path)
    assert stats['committed'] == n

    csv = tmp_path / 'output' / 'archive.csv'
    raw = csv.read_bytes()
    assert raw.endswith(b'\n')

    lines = csv.read_text(encoding='utf-8-sig').splitlines()
    assert lines[0] == HEADER
    assert len(lines) == n + 1

    # Spot-check 10 entries for round-trip correctness
    for line in lines[1:11]:
        key, type_, b64 = line.split(';')
        assert key == 'entity'
        assert type_ == 'record'
        recovered = json.loads(decompress_from_base64(b64))
        assert 'index' in recovered

import json
from pathlib import Path

from src.archiver import (
    compress_to_base64,
    decompress_from_base64,
    ensure_csv_intact,
    write_header_if_needed,
    append_to_csv,
)

HEADER = 'run_id;key;type;suffix;base64_json\n'


def test_compress_decompress_roundtrip():
    original = '{"id": 42, "name": "test"}'
    assert decompress_from_base64(compress_to_base64(original)) == original


def test_compress_output_is_ascii():
    b64 = compress_to_base64('{"x": 1}')
    assert b64.isascii()


def test_compress_no_newlines():
    b64 = compress_to_base64('{"x": 1}')
    assert '\n' not in b64


def test_compress_no_semicolons():
    b64 = compress_to_base64('{"x": 1}')
    assert ';' not in b64


def test_ensure_csv_intact_clean_file(tmp_path):
    csv = tmp_path / 'archive.csv'
    csv.write_bytes(b'key;type;suffix;base64_json\nfoo;bar;s;abc\n')
    ensure_csv_intact(csv)
    assert csv.read_bytes() == b'key;type;suffix;base64_json\nfoo;bar;s;abc\n'


def test_ensure_csv_intact_partial_line(tmp_path):
    csv = tmp_path / 'archive.csv'
    csv.write_bytes(b'key;type;suffix;base64_json\nfoo;bar;s;abc\nbaz;qux;s;PARTIAL')
    ensure_csv_intact(csv)
    assert csv.read_bytes() == b'key;type;suffix;base64_json\nfoo;bar;s;abc\n'


def test_ensure_csv_intact_empty_file(tmp_path):
    csv = tmp_path / 'archive.csv'
    csv.write_bytes(b'')
    ensure_csv_intact(csv)
    assert csv.read_bytes() == b''


def test_ensure_csv_intact_nonexistent(tmp_path):
    ensure_csv_intact(tmp_path / 'missing.csv')  # must not raise


def test_write_header_creates_file(tmp_path):
    csv = tmp_path / 'archive.csv'
    write_header_if_needed(csv)
    content = csv.read_text(encoding='utf-8-sig')
    assert content == HEADER


def test_write_header_no_op_if_exists(tmp_path):
    csv = tmp_path / 'archive.csv'
    csv.write_text('existing content\n', encoding='utf-8')
    write_header_if_needed(csv)
    assert csv.read_text(encoding='utf-8') == 'existing content\n'


def test_append_to_csv(tmp_path):
    csv = tmp_path / 'archive.csv'
    write_header_if_needed(csv)
    append_to_csv(csv, 'run1', 'mykey', 'mytype', 'mysuffix', 'b64data')
    lines = csv.read_text(encoding='utf-8-sig').splitlines()
    assert lines[0] == HEADER.strip()
    assert lines[1] == 'run1;mykey;mytype;mysuffix;b64data'


def test_append_to_csv_empty_suffix(tmp_path):
    csv = tmp_path / 'archive.csv'
    write_header_if_needed(csv)
    append_to_csv(csv, 'run1', 'mykey', 'mytype', '', 'b64data')
    lines = csv.read_text(encoding='utf-8-sig').splitlines()
    assert lines[1] == 'run1;mykey;mytype;;b64data'


def test_append_multiple_entries(tmp_path):
    csv = tmp_path / 'archive.csv'
    write_header_if_needed(csv)
    for i in range(5):
        append_to_csv(csv, 'run1', f'k{i}', f't{i}', f's{i}', f'b{i}')
    lines = csv.read_text(encoding='utf-8-sig').splitlines()
    assert len(lines) == 6  # header + 5 entries

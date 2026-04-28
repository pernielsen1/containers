import json
import pytest
from pathlib import Path

from src.extractor import Extractor
from src.archiver import compress_to_base64, write_header_if_needed, append_to_csv


def make_csv(tmp_path: Path, entries: list[tuple[str, str, str]]) -> Path:
    csv = tmp_path / 'archive.csv'
    write_header_if_needed(csv)
    for key, type_, payload in entries:
        append_to_csv(csv, key, type_, compress_to_base64(payload))
    return csv


def test_extract_returns_correct_json(tmp_path):
    payload = '{"amount": 500}'
    csv = make_csv(tmp_path, [('account', 'loan', payload)])
    result = Extractor(csv).extract('account', 'loan')
    assert json.loads(result) == {"amount": 500}


def test_extract_first_match_when_duplicates(tmp_path):
    csv = make_csv(tmp_path, [
        ('k', 't', '{"v": 1}'),
        ('k', 't', '{"v": 2}'),
    ])
    result = Extractor(csv).extract('k', 't')
    assert json.loads(result)['v'] == 1


def test_extract_selects_correct_entry_among_many(tmp_path):
    csv = make_csv(tmp_path, [
        ('a', 'x', '{"n": 1}'),
        ('b', 'y', '{"n": 2}'),
        ('c', 'z', '{"n": 3}'),
    ])
    assert json.loads(Extractor(csv).extract('b', 'y'))['n'] == 2


def test_extract_key_not_found_raises(tmp_path):
    csv = make_csv(tmp_path, [('a', 'b', '{"x": 1}')])
    with pytest.raises(KeyError):
        Extractor(csv).extract('missing', 'b')


def test_extract_type_not_found_raises(tmp_path):
    csv = make_csv(tmp_path, [('a', 'b', '{"x": 1}')])
    with pytest.raises(KeyError):
        Extractor(csv).extract('a', 'missing')


def test_extract_preserves_complex_json(tmp_path):
    payload = json.dumps({"nested": {"list": [1, 2, 3], "flag": True}, "null": None})
    csv = make_csv(tmp_path, [('obj', 'complex', payload)])
    result = Extractor(csv).extract('obj', 'complex')
    assert json.loads(result) == json.loads(payload)

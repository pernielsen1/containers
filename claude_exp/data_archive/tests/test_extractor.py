import json
import pytest
from pathlib import Path

from src.extractor import Extractor
from src.archiver import compress_to_base64, write_header_if_needed, append_to_csv


def make_csv(tmp_path: Path, entries: list[tuple[str, str, str, str]]) -> Path:
    """entries: (key, type, suffix, payload)"""
    csv = tmp_path / 'archive.csv'
    write_header_if_needed(csv)
    for key, type_, suffix, payload in entries:
        append_to_csv(csv, 'test_run', key, type_, suffix, compress_to_base64(payload))
    return csv


def test_extract_returns_correct_json(tmp_path):
    payload = '{"amount": 500}'
    csv = make_csv(tmp_path, [('account', 'loan', 'abc', payload)])
    result = Extractor(csv).extract('account', 'loan')
    assert json.loads(result) == {"amount": 500}


def test_extract_latest_picks_highest_suffix(tmp_path):
    csv = make_csv(tmp_path, [
        ('k', 't', '350575093',     '{"v": 1}'),
        ('k', 't', '350575093._v1', '{"v": 2}'),
    ])
    _, result = Extractor(csv).extract_latest('k', 't')
    assert json.loads(result)['v'] == 2


def test_extract_latest_empty_vs_suffix(tmp_path):
    csv = make_csv(tmp_path, [
        ('k', 't', '',    '{"v": 1}'),
        ('k', 't', '_v1', '{"v": 2}'),
    ])
    suffix, result = Extractor(csv).extract_latest('k', 't')
    assert suffix == '_v1'
    assert json.loads(result)['v'] == 2


def test_extract_all_returns_all_versions(tmp_path):
    csv = make_csv(tmp_path, [
        ('k', 't', 'abc', '{"v": 1}'),
        ('k', 't', 'abd', '{"v": 2}'),
        ('k', 't', 'abe', '{"v": 3}'),
    ])
    entries = Extractor(csv).extract_all('k', 't')
    assert len(entries) == 3
    assert [json.loads(j)['v'] for _, j in entries] == [1, 2, 3]


def test_extract_selects_correct_entry_among_many(tmp_path):
    csv = make_csv(tmp_path, [
        ('a', 'x', 's1', '{"n": 1}'),
        ('b', 'y', 's2', '{"n": 2}'),
        ('c', 'z', 's3', '{"n": 3}'),
    ])
    assert json.loads(Extractor(csv).extract('b', 'y'))['n'] == 2


def test_extract_key_not_found_raises(tmp_path):
    csv = make_csv(tmp_path, [('a', 'b', 's', '{"x": 1}')])
    with pytest.raises(KeyError):
        Extractor(csv).extract('missing', 'b')


def test_extract_type_not_found_raises(tmp_path):
    csv = make_csv(tmp_path, [('a', 'b', 's', '{"x": 1}')])
    with pytest.raises(KeyError):
        Extractor(csv).extract('a', 'missing')


def test_extract_preserves_complex_json(tmp_path):
    payload = json.dumps({"nested": {"list": [1, 2, 3], "flag": True}, "null": None})
    csv = make_csv(tmp_path, [('obj', 'complex', 'suf', payload)])
    result = Extractor(csv).extract('obj', 'complex')
    assert json.loads(result) == json.loads(payload)

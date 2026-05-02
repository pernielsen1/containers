import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.merger import Merger

HEADER = 'key;type;name'


def make_pass2(path: Path, rows: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join([HEADER] + rows) + '\n', encoding='utf-8-sig')
    return path


def test_merge_creates_new_file(tmp_path):
    pass2 = make_pass2(tmp_path / 'extracted.csv', ['duns;company;Acme'])
    full = tmp_path / 'full_extract.csv'

    n = Merger().merge(pass2, full)

    assert n == 1
    lines = full.read_text(encoding='utf-8-sig').splitlines()
    assert lines[0] == HEADER
    assert lines[1] == 'duns;company;Acme'


def test_merge_appends_to_existing(tmp_path):
    pass2a = make_pass2(tmp_path / 'a.csv', ['duns;company;Acme'])
    pass2b = make_pass2(tmp_path / 'b.csv', ['duns;company;Beta'])
    full = tmp_path / 'full_extract.csv'

    Merger().merge(pass2a, full)
    n = Merger().merge(pass2b, full)

    assert n == 1
    lines = full.read_text(encoding='utf-8-sig').splitlines()
    assert lines.count(HEADER) == 1
    assert 'duns;company;Acme' in lines
    assert 'duns;company;Beta' in lines
    assert len(lines) == 3


def test_merge_allows_duplicates(tmp_path):
    pass2 = make_pass2(tmp_path / 'extracted.csv', ['duns;company;Acme'])
    full = tmp_path / 'full_extract.csv'

    Merger().merge(pass2, full)
    Merger().merge(pass2, full)

    lines = full.read_text(encoding='utf-8-sig').splitlines()
    assert lines.count('duns;company;Acme') == 2


def test_merge_interrupted_leaves_original_intact(tmp_path):
    pass2a = make_pass2(tmp_path / 'a.csv', ['duns;company;Acme'])
    pass2b = make_pass2(tmp_path / 'b.csv', ['duns;company;Beta'])
    full = tmp_path / 'full_extract.csv'
    Merger().merge(pass2a, full)
    original = full.read_bytes()

    with patch('src.merger.os.replace', side_effect=OSError('simulated crash')):
        with pytest.raises(OSError, match='simulated crash'):
            Merger().merge(pass2b, full)

    assert full.read_bytes() == original
    assert not (tmp_path / 'full_extract.csv.tmp').exists()

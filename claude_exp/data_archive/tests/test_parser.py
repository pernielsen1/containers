import pytest
from src.parser import parse_filename


def test_standard_pattern():
    assert parse_filename('foo_bar_20240101.json') == ('foo', 'bar')


def test_long_suffix():
    assert parse_filename('account_loan_2024-01-01T12:00:00Z.json') == ('account', 'loan')


def test_no_suffix():
    assert parse_filename('key_type.json') == ('key', 'type')


def test_numeric_key_and_type():
    assert parse_filename('123_456_xyz.json') == ('123', '456')


def test_missing_underscore_raises():
    with pytest.raises(ValueError):
        parse_filename('nounderscore.json')


def test_stem_only_no_extension():
    assert parse_filename('a_b') == ('a', 'b')

import pytest
from src.parser import parse_filename


def test_standard_pattern():
    assert parse_filename('foo_bar_20240101.json') == ('foo', 'bar', '20240101')


def test_long_suffix():
    assert parse_filename('account_loan_2024-01-01T12:00:00Z.json') == ('account', 'loan', '2024-01-01T12:00:00Z')


def test_no_suffix():
    assert parse_filename('key_type.json') == ('key', 'type', '')


def test_numeric_key_and_type():
    assert parse_filename('123_456_xyz.json') == ('123', '456', 'xyz')


def test_missing_underscore_raises():
    with pytest.raises(ValueError):
        parse_filename('nounderscore.json')


def test_stem_only_no_extension():
    assert parse_filename('a_b') == ('a', 'b', '')


def test_version_suffix():
    assert parse_filename('duns_company_350575093._v1.json') == ('duns', 'company', '350575093._v1')


def test_timestamp_suffix():
    assert parse_filename('duns_company_350575093_20260412_195712.json') == ('duns', 'company', '350575093_20260412_195712')

from src.validator import validate_json


def test_valid_object():
    assert validate_json('{"a": 1, "b": "hello"}') is True


def test_valid_array():
    assert validate_json('[1, 2, 3]') is True


def test_valid_nested():
    assert validate_json('{"x": {"y": [1, null, true]}}') is True


def test_valid_empty_object():
    assert validate_json('{}') is True


def test_valid_empty_array():
    assert validate_json('[]') is True


def test_invalid_truncated():
    assert validate_json('{"a": 1,') is False


def test_invalid_not_json():
    assert validate_json('not json at all') is False


def test_invalid_empty_string():
    assert validate_json('') is False


def test_invalid_bare_string():
    assert validate_json('"just a string"') is True  # valid JSON per spec


def test_invalid_trailing_comma():
    assert validate_json('{"a": 1,}') is False

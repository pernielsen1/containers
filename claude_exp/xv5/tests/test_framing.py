import socket

import pytest

from shared.framing import read_message, write_message


@pytest.mark.parametrize(
    "length_field_type",
    ["BIG_ENDIAN", "LITTLE_ENDIAN", "ASCII", "EBCDIC"],
)
def test_roundtrip_all_length_field_types(length_field_type):
    a, b = socket.socketpair()
    cfg = {"header_hex": "", "length_field_type": length_field_type, "length_field_bytes": 4}
    payload = b"hello world"
    try:
        write_message(a, payload, cfg)
        assert read_message(b, cfg) == payload
    finally:
        a.close()
        b.close()


def test_roundtrip_with_fixed_header():
    a, b = socket.socketpair()
    cfg = {"header_hex": "DEADBEEF", "length_field_type": "ASCII", "length_field_bytes": 4}
    payload = b"abc123"
    try:
        write_message(a, payload, cfg)
        assert read_message(b, cfg) == payload
    finally:
        a.close()
        b.close()


def test_max_message_bytes_rejection():
    a, b = socket.socketpair()
    cfg = {
        "header_hex": "",
        "length_field_type": "ASCII",
        "length_field_bytes": 4,
        "max_message_bytes": 5,
    }
    payload = b"this payload is too long"
    try:
        write_message(a, payload, cfg)
        with pytest.raises(ConnectionError):
            read_message(b, cfg)
    finally:
        a.close()
        b.close()


def test_disconnect_raises_connection_error():
    a, b = socket.socketpair()
    cfg = {"header_hex": "", "length_field_type": "ASCII", "length_field_bytes": 4}
    a.close()
    with pytest.raises(ConnectionError):
        read_message(b, cfg)
    b.close()

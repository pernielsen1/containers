import socket
import threading
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared.framing import read_message, write_message

BE4  = {"header_hex": "",     "length_field_type": "BIG_ENDIAN",    "length_field_bytes": 4}
LE4  = {"header_hex": "",     "length_field_type": "LITTLE_ENDIAN", "length_field_bytes": 4}
AS4  = {"header_hex": "",     "length_field_type": "ASCII",         "length_field_bytes": 4}
EB4  = {"header_hex": "",     "length_field_type": "EBCDIC",        "length_field_bytes": 4}
HDR  = {"header_hex": "FFFF", "length_field_type": "BIG_ENDIAN",    "length_field_bytes": 4}


def roundtrip(cfg, data):
    a, b = socket.socketpair()
    try:
        write_message(a, data, cfg)
        return read_message(b, cfg)
    finally:
        a.close()
        b.close()


def test_big_endian():
    assert roundtrip(BE4, b"hello world") == b"hello world"

def test_little_endian():
    assert roundtrip(LE4, b"hello world") == b"hello world"

def test_ascii():
    assert roundtrip(AS4, b"hello world") == b"hello world"

def test_ebcdic():
    assert roundtrip(EB4, b"hello world") == b"hello world"

def test_with_header():
    assert roundtrip(HDR, b"hello world") == b"hello world"

def test_empty_message():
    assert roundtrip(BE4, b"") == b""

def test_large_message():
    data = bytes(range(256)) * 39  # 9984 bytes
    assert roundtrip(AS4, data) == data

def test_ascii_wire_format():
    # 42 bytes → b'0042'
    a, b = socket.socketpair()
    try:
        write_message(a, b"x" * 42, AS4)
        header = b.recv(4)
        assert header == b"0042"
    finally:
        a.close()
        b.close()

def test_big_endian_wire_format():
    a, b = socket.socketpair()
    try:
        write_message(a, b"x" * 42, BE4)
        header = b.recv(4)
        assert header == b"\x00\x00\x00\x2a"
    finally:
        a.close()
        b.close()

def test_header_sent_on_wire():
    a, b = socket.socketpair()
    try:
        write_message(a, b"hi", HDR)
        raw = b.recv(8)
        assert raw[:2] == bytes.fromhex("FFFF")
    finally:
        a.close()
        b.close()

def test_connection_closed_raises():
    a, b = socket.socketpair()
    a.close()
    with pytest.raises(ConnectionError):
        read_message(b, BE4)
    b.close()

def test_two_messages_sequential():
    a, b = socket.socketpair()
    try:
        write_message(a, b"first", BE4)
        write_message(a, b"second", BE4)
        assert read_message(b, BE4) == b"first"
        assert read_message(b, BE4) == b"second"
    finally:
        a.close()
        b.close()

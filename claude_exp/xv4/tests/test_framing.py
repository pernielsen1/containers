import io
import socket
import sys
import os
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from shared.framing import read_message, write_message


def loopback_pair():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    client = socket.create_connection(("127.0.0.1", port))
    server_conn, _ = srv.accept()
    srv.close()
    return client, server_conn


@pytest.mark.parametrize("lf_type,lf_bytes", [
    ("BIG_ENDIAN", 2),
    ("LITTLE_ENDIAN", 2),
    ("ASCII", 4),
    ("EBCDIC", 4),
])
def test_framing_roundtrip(lf_type, lf_bytes):
    sender, receiver = loopback_pair()
    cfg = {"header_hex": "", "length_field_type": lf_type, "length_field_bytes": lf_bytes}
    payload = b"hello world"
    write_message(sender, payload, cfg)
    result = read_message(receiver, cfg)
    assert result == payload
    sender.close()
    receiver.close()


def test_framing_with_header():
    sender, receiver = loopback_pair()
    cfg = {"header_hex": "AABB", "length_field_type": "ASCII", "length_field_bytes": 4}
    payload = b"test data"
    write_message(sender, payload, cfg)
    result = read_message(receiver, cfg)
    assert result == payload
    sender.close()
    receiver.close()


def test_max_message_bytes_rejected():
    sender, receiver = loopback_pair()
    cfg = {"header_hex": "", "length_field_type": "ASCII", "length_field_bytes": 4, "max_message_bytes": 5}
    payload = b"x" * 100
    write_message(sender, payload, cfg)
    with pytest.raises(ConnectionError, match="max_message_bytes"):
        read_message(receiver, cfg)
    sender.close()
    receiver.close()

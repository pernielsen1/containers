import socket
import threading

import pytest

from shared.framing import read_message, write_message


def _socketpair():
    a, b = socket.socketpair()
    return a, b


@pytest.mark.parametrize(
    "length_field_type,length_field_bytes",
    [
        ("BIG_ENDIAN", 4),
        ("LITTLE_ENDIAN", 4),
        ("ASCII", 4),
        ("EBCDIC", 4),
    ],
)
def test_roundtrip_no_header(length_field_type, length_field_bytes):
    sender, receiver = _socketpair()
    cfg = {
        "header_hex": "",
        "length_field_type": length_field_type,
        "length_field_bytes": length_field_bytes,
    }
    payload = b"hello world, this is a test payload"

    write_message(sender, payload, cfg)
    received = read_message(receiver, cfg)

    assert received == payload
    sender.close()
    receiver.close()


def test_roundtrip_with_header():
    sender, receiver = _socketpair()
    cfg = {
        "header_hex": "DEADBEEF",
        "length_field_type": "BIG_ENDIAN",
        "length_field_bytes": 2,
    }
    payload = b"payload-with-header"

    write_message(sender, payload, cfg)
    received = read_message(receiver, cfg)

    assert received == payload
    sender.close()
    receiver.close()


def test_max_message_bytes_rejection():
    sender, receiver = _socketpair()
    cfg = {
        "header_hex": "",
        "length_field_type": "BIG_ENDIAN",
        "length_field_bytes": 4,
        "max_message_bytes": 10,
    }

    # Manually craft a frame declaring a length bigger than max_message_bytes,
    # without ever sending the (nonexistent) payload — read_message must fail
    # fast rather than blocking on _recv_exact waiting for bytes that never arrive.
    sender.sendall((1000).to_bytes(4, "big"))

    with pytest.raises(ConnectionError):
        read_message(receiver, cfg)

    sender.close()
    receiver.close()


def test_read_message_raises_on_closed_connection():
    sender, receiver = _socketpair()
    cfg = {
        "header_hex": "",
        "length_field_type": "BIG_ENDIAN",
        "length_field_bytes": 4,
    }
    sender.close()

    with pytest.raises(ConnectionError):
        read_message(receiver, cfg)

    receiver.close()


def test_roundtrip_over_real_tcp_socket():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    cfg = {
        "header_hex": "",
        "length_field_type": "ASCII",
        "length_field_bytes": 4,
    }
    payload = b"0100message-over-tcp"
    received = {}

    def server_thread():
        conn, _ = srv.accept()
        received["data"] = read_message(conn, cfg)
        conn.close()

    t = threading.Thread(target=server_thread)
    t.start()

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect(("127.0.0.1", port))
    write_message(client, payload, cfg)
    client.close()

    t.join(timeout=5)
    srv.close()

    assert received["data"] == payload

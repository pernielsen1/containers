import struct


IRM_HEADER_LEN = 28
_TRANS_CODE_LEN = 8
_CLIENTID_OFFSET = 20   # byte offset of IRM_CLIENTID within the 28-byte IMS header


def to_ebcdic(s, length):
    return s.encode("cp500").ljust(length)[:length]


def _recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except OSError as e:
            raise ConnectionError(str(e)) from e
        if not chunk:
            raise ConnectionError("Connection closed")
        buf.extend(chunk)
    return bytes(buf)


def build_frame(irm_f0, irm_id, client_id, mti=None, data=b""):
    """Build a complete IMS Connect wire frame (llll + IMS header + optional TRANS_CODE + data)."""
    payload_len = IRM_HEADER_LEN + (_TRANS_CODE_LEN + len(data) if data else 0)
    header = (
        struct.pack(">H", IRM_HEADER_LEN)
        + bytes([0x04, irm_f0])
        + irm_id
        + b"\x00\x00\x00\x00"           # IRM_NAK_RSNCDE(2) + IRM_RES(2)
        + bytes([0x00, 0x15, 0x10, 0x01])  # IRM_F5, IRM_TIMER, IRM_SOCT, IRM_ES
        + client_id
    )
    body = (to_ebcdic(f"TRAN{mti}", _TRANS_CODE_LEN) + data) if data else b""
    return struct.pack(">I", payload_len) + header + body


def write_response(sock, data):
    """Send a downstream response (llll + ISO data, no IMS header)."""
    sock.sendall(struct.pack(">I", len(data)) + data)


def read_response(sock):
    """Read a downstream response (llll + ISO data). Returns the ISO data bytes."""
    raw = _recv_exact(sock, 4)
    length = struct.unpack(">I", raw)[0]
    return _recv_exact(sock, length)


def read_request(sock):
    """Read an IMS Connect request frame. Returns (irm_f0, client_id_bytes, iso_data_bytes)."""
    raw = _recv_exact(sock, 4)
    length = struct.unpack(">I", raw)[0]
    payload = _recv_exact(sock, length)
    irm_f0 = payload[3]
    client_id = payload[_CLIENTID_OFFSET: _CLIENTID_OFFSET + 8]
    iso_data = payload[IRM_HEADER_LEN + _TRANS_CODE_LEN:] if length > IRM_HEADER_LEN else b""
    return irm_f0, client_id, iso_data

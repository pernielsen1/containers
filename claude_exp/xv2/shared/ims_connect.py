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


PING_TRANSCODE = to_ebcdic("PING0001", _TRANS_CODE_LEN)


def build_frame(irm_f0, irm_id, client_id, mti=None, data=b"", transcode=None):
    """Build a complete IMS Connect wire frame (llll + IMS header + optional TRANS_CODE + data).

    transcode: 8-byte EBCDIC override; defaults to b'TRAN'+mti when data is present.
    """
    payload_len = IRM_HEADER_LEN + (_TRANS_CODE_LEN + len(data) if data else 0)
    header = (
        struct.pack(">H", IRM_HEADER_LEN)
        + bytes([0x04, irm_f0])
        + irm_id
        + b"\x00\x00\x00\x00"           # IRM_NAK_RSNCDE(2) + IRM_RES(2)
        + bytes([0x00, 0x15, 0x10, 0x01])  # IRM_F5, IRM_TIMER, IRM_SOCT, IRM_ES
        + client_id
    )
    if data:
        tc = transcode if transcode is not None else to_ebcdic(f"TRAN{mti}", _TRANS_CODE_LEN)
        body = tc + data
    else:
        body = b""
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
    """Read an IMS Connect request frame. Returns (irm_f0, client_id_bytes, transcode_bytes, iso_data_bytes)."""
    raw = _recv_exact(sock, 4)
    length = struct.unpack(">I", raw)[0]
    payload = _recv_exact(sock, length)
    irm_f0 = payload[3]
    client_id = payload[_CLIENTID_OFFSET: _CLIENTID_OFFSET + 8]
    if length > IRM_HEADER_LEN:
        transcode = payload[IRM_HEADER_LEN: IRM_HEADER_LEN + _TRANS_CODE_LEN]
        iso_data = payload[IRM_HEADER_LEN + _TRANS_CODE_LEN:]
    else:
        transcode = b""
        iso_data = b""
    return irm_f0, client_id, transcode, iso_data

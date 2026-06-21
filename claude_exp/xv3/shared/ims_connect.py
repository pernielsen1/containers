"""IMS Connect wire protocol. The downstream host uses a dual-socket model:
one socket sends requests (to-socket), one receives responses (from-socket)."""

from shared.framing import _recv_exact

IRM_HEADER_LEN = 28
_EBCDIC_SPACE = b"\x40"


def to_ebcdic(s: str, length: int) -> bytes:
    """EBCDIC-encode and left-pad/truncate to exactly `length` bytes."""
    encoded = s.encode("cp500")
    if len(encoded) >= length:
        return encoded[:length]
    return _EBCDIC_SPACE * (length - len(encoded)) + encoded


PING_TRANSCODE = to_ebcdic("PING0001", 8)


def build_frame(irm_f0, irm_id: bytes, client_id: bytes, mti=None, data: bytes = b"", transcode: bytes = None) -> bytes:
    """Build a complete IMS Connect wire frame: 4-byte big-endian length (payload only)
    + 28-byte IMS header + optional TRANS_CODE (8 bytes EBCDIC) + data.
    irm_f0=0x80 -> resume TPIPE (no data). irm_f0=0x00 -> normal request.
    transcode defaults to TRAN+mti when data is present."""
    header = (
        IRM_HEADER_LEN.to_bytes(2, "big")
        + bytes([0x04, irm_f0])
        + irm_id
        + b"\x00\x00\x00\x00"
        + b"\x00\x15\x10\x01"
        + client_id
    )

    body = b""
    if data:
        tc = transcode if transcode is not None else to_ebcdic("TRAN" + (mti or ""), 8)
        body = tc + data

    payload = header + body
    return len(payload).to_bytes(4, "big") + payload


def write_response(sock, data: bytes) -> None:
    """Send downstream response: 4-byte big-endian length + data."""
    sock.sendall(len(data).to_bytes(4, "big") + data)


def read_response(sock) -> bytes:
    """Read downstream response. Returns ISO data bytes only (strips length prefix)."""
    length = int.from_bytes(_recv_exact(sock, 4), "big")
    return _recv_exact(sock, length)


def read_request(sock) -> tuple:
    """Read IMS Connect request. Returns (irm_f0, client_id_bytes, transcode_bytes, iso_data_bytes)."""
    length = int.from_bytes(_recv_exact(sock, 4), "big")
    payload = _recv_exact(sock, length)

    irm_f0 = payload[3]
    client_id = payload[20:28]
    remainder = payload[28:]

    if remainder:
        transcode = remainder[:8]
        iso_data = remainder[8:]
    else:
        transcode = b""
        iso_data = b""

    return irm_f0, client_id, transcode, iso_data

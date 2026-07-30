"""IMS Connect wire protocol. Dual-socket model: to-socket sends requests,
from-socket receives responses."""

from shared.framing import _recv_exact

IRM_HEADER_LEN = 28


def to_ebcdic(s: str, length: int) -> bytes:
    """EBCDIC-encode and left-pad/truncate to exactly `length` bytes."""
    b = s.encode("cp500")
    if len(b) >= length:
        return b[-length:]
    pad = " ".encode("cp500") * (length - len(b))
    return pad + b


PING_TRANSCODE = to_ebcdic("PING0001", 8)


def build_frame(irm_f0, irm_id: bytes, client_id: bytes, mti=None, data: bytes = b"", transcode=None) -> bytes:
    """Build a complete IMS Connect wire frame: 4-byte big-endian length (payload only)
    + 28-byte IMS header + optional TRANS_CODE (8 bytes EBCDIC) + data.
    irm_f0=0x80 -> resume TPIPE (no data). irm_f0=0x00 -> normal request.
    transcode defaults to TRAN+mti when data is present."""
    has_data = len(data) > 0
    if has_data and transcode is None:
        transcode = to_ebcdic(f"TRAN{mti}", 8)

    irm_header = (
        IRM_HEADER_LEN.to_bytes(2, "big")
        + bytes([0x04])
        + bytes([irm_f0])
        + irm_id
        + b"\x00\x00\x00\x00"
        + b"\x00\x15\x10\x01"
        + client_id
    )
    trailer = (transcode + data) if has_data else b""
    payload_len = len(irm_header) + len(trailer)
    return payload_len.to_bytes(4, "big") + irm_header + trailer


def write_response(sock, data: bytes) -> None:
    """Send downstream response: 4-byte big-endian length + data."""
    sock.sendall(len(data).to_bytes(4, "big") + data)


def read_response(sock) -> bytes:
    """Read downstream response. Returns ISO data bytes only (strips length prefix)."""
    len_bytes = _recv_exact(sock, 4)
    length = int.from_bytes(len_bytes, "big")
    return _recv_exact(sock, length)


def read_request(sock) -> tuple:
    """Read IMS Connect request. Returns (irm_f0, client_id_bytes, transcode_bytes, iso_data_bytes)."""
    len_bytes = _recv_exact(sock, 4)
    payload_len = int.from_bytes(len_bytes, "big")
    payload = _recv_exact(sock, payload_len)

    irm_f0 = payload[3]
    client_id = payload[20:28]
    rest = payload[IRM_HEADER_LEN:]
    if rest:
        transcode = rest[:8]
        iso_data = rest[8:]
    else:
        transcode = b""
        iso_data = b""
    return irm_f0, client_id, transcode, iso_data

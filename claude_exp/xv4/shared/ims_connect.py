import struct
from shared.framing import _recv_exact

IRM_HEADER_LEN = 28
PING_TRANSCODE = "PING0001".encode("cp500")


def to_ebcdic(s: str, length: int) -> bytes:
    encoded = s.encode("cp500")
    if len(encoded) >= length:
        return encoded[:length]
    return encoded.ljust(length, b"\x40")  # EBCDIC space


def build_frame(irm_f0, irm_id, client_id, mti=None, data=b"", transcode=None) -> bytes:
    if transcode is None and data:
        transcode = to_ebcdic("TRAN" + (mti or ""), 8)

    payload = (
        struct.pack(">H", IRM_HEADER_LEN)  # 2B
        + b"\x04"                           # 1B
        + bytes([irm_f0])                   # 1B
        + irm_id                            # 8B EBCDIC
        + b"\x00\x00\x00\x00"              # IRM_NAK_RSNCDE(2) + IRM_RES(2)
        + b"\x00\x15\x10\x01"              # IRM_F5, IRM_TIMER, IRM_SOCT, IRM_ES
        + client_id                         # 8B EBCDIC
    )
    if data:
        payload += (transcode or b"\x40" * 8) + data

    frame = struct.pack(">I", len(payload)) + payload
    return frame


def write_response(sock, data: bytes) -> None:
    sock.sendall(struct.pack(">I", len(data)) + data)


def read_response(sock) -> bytes:
    raw = _recv_exact(sock, 4)
    length = struct.unpack(">I", raw)[0]
    return _recv_exact(sock, length)


def read_request(sock) -> tuple:
    raw = _recv_exact(sock, 4)
    length = struct.unpack(">I", raw)[0]
    payload = _recv_exact(sock, length)

    # IRM header: 2B header_len + 1B 0x04 + 1B irm_f0 + 8B irm_id + 4B zeros + 4B flags + 8B client_id
    irm_f0 = payload[3]
    irm_id_bytes = payload[4:12]
    client_id_bytes = payload[20:28]

    remaining = payload[28:]
    if remaining:
        transcode_bytes = remaining[:8]
        iso_data_bytes = remaining[8:]
    else:
        transcode_bytes = b""
        iso_data_bytes = b""

    return irm_f0, client_id_bytes, transcode_bytes, iso_data_bytes

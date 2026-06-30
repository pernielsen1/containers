import struct


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except OSError as e:
            raise ConnectionError(f"socket error during recv: {e}") from e
        if not chunk:
            raise ConnectionError("connection closed while reading")
        buf += chunk
    return buf


def read_message(sock, cfg) -> bytes:
    max_bytes = cfg.get("max_message_bytes", 65536)

    header_hex = cfg.get("header_hex", "")
    if header_hex:
        header_bytes = bytes.fromhex(header_hex)
        _recv_exact(sock, len(header_bytes))

    lf_bytes = cfg["length_field_bytes"]
    lf_type = cfg["length_field_type"]
    raw_len = _recv_exact(sock, lf_bytes)

    if lf_type == "BIG_ENDIAN":
        length = int.from_bytes(raw_len, "big")
    elif lf_type == "LITTLE_ENDIAN":
        length = int.from_bytes(raw_len, "little")
    elif lf_type == "ASCII":
        length = int(raw_len.decode("ascii"))
    elif lf_type == "EBCDIC":
        length = int(raw_len.decode("cp500"))
    else:
        raise ValueError(f"unknown length_field_type: {lf_type}")

    if length > max_bytes:
        raise ConnectionError(
            f"message length {length} exceeds max_message_bytes {max_bytes}"
        )

    return _recv_exact(sock, length)


def write_message(sock, data: bytes, cfg) -> None:
    header_hex = cfg.get("header_hex", "")
    header_bytes = bytes.fromhex(header_hex) if header_hex else b""

    lf_bytes = cfg["length_field_bytes"]
    lf_type = cfg["length_field_type"]
    length = len(data)

    if lf_type == "BIG_ENDIAN":
        raw_len = length.to_bytes(lf_bytes, "big")
    elif lf_type == "LITTLE_ENDIAN":
        raw_len = length.to_bytes(lf_bytes, "little")
    elif lf_type == "ASCII":
        raw_len = str(length).zfill(lf_bytes).encode("ascii")
    elif lf_type == "EBCDIC":
        raw_len = str(length).zfill(lf_bytes).encode("cp500")
    else:
        raise ValueError(f"unknown length_field_type: {lf_type}")

    sock.sendall(header_bytes + raw_len + data)

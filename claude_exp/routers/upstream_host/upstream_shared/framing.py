"""Length-prefixed TCP framing: optional fixed header + length field + payload."""

DEFAULT_MAX_MESSAGE_BYTES = 65536


def _recv_exact(sock, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except OSError as e:
            raise ConnectionError(f"recv failed: {e}") from e
        if not chunk:
            raise ConnectionError("connection closed while reading")
        buf.extend(chunk)
    return bytes(buf)


def _encode_length(length: int, length_field_bytes: int, length_field_type: str) -> bytes:
    if length_field_type == "BIG_ENDIAN":
        return length.to_bytes(length_field_bytes, "big")
    if length_field_type == "LITTLE_ENDIAN":
        return length.to_bytes(length_field_bytes, "little")
    if length_field_type == "ASCII":
        return str(length).zfill(length_field_bytes).encode("ascii")
    if length_field_type == "EBCDIC":
        return str(length).zfill(length_field_bytes).encode("cp500")
    raise ValueError(f"unknown length_field_type: {length_field_type}")


def _decode_length(raw: bytes, length_field_type: str) -> int:
    if length_field_type == "BIG_ENDIAN":
        return int.from_bytes(raw, "big")
    if length_field_type == "LITTLE_ENDIAN":
        return int.from_bytes(raw, "little")
    if length_field_type == "ASCII":
        return int(raw.decode("ascii"))
    if length_field_type == "EBCDIC":
        return int(raw.decode("cp500"))
    raise ValueError(f"unknown length_field_type: {length_field_type}")


def read_message(sock, cfg: dict) -> bytes:
    """cfg keys: header_hex (str, may be ""), length_field_bytes (int),
    length_field_type ("BIG_ENDIAN"|"LITTLE_ENDIAN"|"ASCII"|"EBCDIC"),
    max_message_bytes (int, optional - default 65536).
    Reads optional fixed header, reads length field, reads payload.
    Raises ConnectionError immediately if the decoded length exceeds max_message_bytes,
    instead of letting _recv_exact block waiting for bytes that may never arrive - a corrupt
    or hostile length field must fail fast and drop the connection, not hang its read thread
    forever.
    """
    header_hex = cfg.get("header_hex", "") or ""
    if header_hex:
        header_len = len(bytes.fromhex(header_hex))
        _recv_exact(sock, header_len)

    length_field_bytes = cfg["length_field_bytes"]
    length_field_type = cfg["length_field_type"]
    max_message_bytes = cfg.get("max_message_bytes", DEFAULT_MAX_MESSAGE_BYTES)

    raw_len = _recv_exact(sock, length_field_bytes)
    length = _decode_length(raw_len, length_field_type)
    if length > max_message_bytes:
        raise ConnectionError(
            f"declared message length {length} exceeds max_message_bytes {max_message_bytes}"
        )
    return _recv_exact(sock, length)


def write_message(sock, data: bytes, cfg: dict) -> None:
    """Writes header + encoded length + data in one sendall."""
    header_hex = cfg.get("header_hex", "") or ""
    header = bytes.fromhex(header_hex) if header_hex else b""
    length_bytes = _encode_length(len(data), cfg["length_field_bytes"], cfg["length_field_type"])
    sock.sendall(header + length_bytes + data)

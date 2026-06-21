"""Length-prefixed TCP framing. No state; two pure functions."""

DEFAULT_MAX_MESSAGE_BYTES = 65536


def _recv_exact(sock, n: int) -> bytes:
    chunks = []
    remaining = n
    while remaining > 0:
        try:
            chunk = sock.recv(remaining)
        except OSError as e:
            # Normalizes a local close racing this blocked read (e.g. EBADF, which is not
            # itself a ConnectionError subclass) into the same exception type callers
            # already handle for a remote disconnect — one exception type to catch either way.
            raise ConnectionError(f"socket error while reading: {e}") from e
        if not chunk:
            raise ConnectionError("connection closed while reading")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


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


def _decode_length(data: bytes, length_field_type: str) -> int:
    if length_field_type == "BIG_ENDIAN":
        return int.from_bytes(data, "big")
    if length_field_type == "LITTLE_ENDIAN":
        return int.from_bytes(data, "little")
    if length_field_type == "ASCII":
        return int(data.decode("ascii"))
    if length_field_type == "EBCDIC":
        return int(data.decode("cp500"))
    raise ValueError(f"unknown length_field_type: {length_field_type}")


def read_message(sock, cfg) -> bytes:
    """cfg keys: header_hex (str, may be ""), length_field_bytes (int),
    length_field_type ("BIG_ENDIAN"|"LITTLE_ENDIAN"|"ASCII"|"EBCDIC"),
    max_message_bytes (int, optional — default 65536).
    Reads optional fixed header, reads length field, reads payload.
    Raises ConnectionError immediately if the decoded length exceeds max_message_bytes,
    instead of letting _recv_exact block waiting for bytes that may never arrive — a corrupt
    or hostile length field must fail fast and drop the connection, not hang its read thread
    forever."""
    header_hex = cfg.get("header_hex", "")
    if header_hex:
        header_len = len(header_hex) // 2
        _recv_exact(sock, header_len)

    length_field_bytes = cfg["length_field_bytes"]
    length_field_type = cfg["length_field_type"]
    max_message_bytes = cfg.get("max_message_bytes", DEFAULT_MAX_MESSAGE_BYTES)

    length_bytes = _recv_exact(sock, length_field_bytes)
    length = _decode_length(length_bytes, length_field_type)

    if length > max_message_bytes:
        raise ConnectionError(
            f"declared message length {length} exceeds max_message_bytes {max_message_bytes}"
        )

    return _recv_exact(sock, length)


def write_message(sock, data: bytes, cfg) -> None:
    """Writes header + encoded length + data in one sendall."""
    header_hex = cfg.get("header_hex", "")
    parts = []
    if header_hex:
        parts.append(bytes.fromhex(header_hex))

    length_field_bytes = cfg["length_field_bytes"]
    length_field_type = cfg["length_field_type"]
    parts.append(_encode_length(len(data), length_field_bytes, length_field_type))
    parts.append(data)

    sock.sendall(b"".join(parts))

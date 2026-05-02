import socket


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


def read_message(sock, cfg):
    header = bytes.fromhex(cfg.get("header_hex", ""))
    if header:
        _recv_exact(sock, len(header))

    n = cfg["length_field_bytes"]
    raw = _recv_exact(sock, n)

    ltype = cfg["length_field_type"].upper()
    if ltype == "BIG_ENDIAN":
        length = int.from_bytes(raw, "big")
    elif ltype == "LITTLE_ENDIAN":
        length = int.from_bytes(raw, "little")
    elif ltype == "ASCII":
        length = int(raw.decode("ascii"))
    elif ltype == "EBCDIC":
        length = int(raw.decode("cp500"))
    else:
        raise ValueError(f"Unknown length_field_type: {cfg['length_field_type']}")

    return _recv_exact(sock, length)


def write_message(sock, data, cfg):
    header = bytes.fromhex(cfg.get("header_hex", ""))
    length = len(data)
    n = cfg["length_field_bytes"]

    ltype = cfg["length_field_type"].upper()
    if ltype == "BIG_ENDIAN":
        raw = length.to_bytes(n, "big")
    elif ltype == "LITTLE_ENDIAN":
        raw = length.to_bytes(n, "little")
    elif ltype == "ASCII":
        raw = str(length).zfill(n).encode("ascii")
    elif ltype == "EBCDIC":
        raw = str(length).zfill(n).encode("cp500")
    else:
        raise ValueError(f"Unknown length_field_type: {cfg['length_field_type']}")

    sock.sendall(header + raw + data)

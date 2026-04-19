# iso8583 skill

Reference and patterns for working with ISO 8583 authorization messages using the `pyiso8583` package.

## Package: pyiso8583

```
pip install pyiso8583
```

Import as:
```python
import iso8583
```

> Pylance may show an unresolved import warning — the package installs fine, it just lacks type stubs.

---

## Core API

### Encode (dict → bytes)

```python
encoded_bytes, doc_enc = iso8583.encode(doc_dec, spec=my_spec)
```

- **First** return value is the `bytearray` to send over the wire.
- **Second** is an internal dict of encoded field representations (rarely needed).
- Common mistake: unpacking as `_, encoded` gives you the dict, not the bytes.

### Decode (bytes → dict)

```python
doc_dec, doc_enc = iso8583.decode(raw_bytes, spec=my_spec)
```

- **First** return value is the human-readable decoded dict (field id → string value).
- **Second** is the raw encoded representation dict.

---

## Spec format

Each field in the spec is a dict with keys like:

```python
my_spec = {
    "h": {"data_enc": "ascii", "len_enc": "ascii", "len_type": 0, "max_len": 4, "desc": "MTI"},
    "p": {"data_enc": "b",     "len_enc": "b",     "len_type": 0, "max_len": 8, "desc": "Bitmap"},
    "2": {"data_enc": "ascii", "len_enc": "ascii", "len_type": 2, "max_len": 19, "desc": "PAN"},
    ...
}
```

- `"h"` = MTI (message type indicator), `"p"` = primary bitmap, `"1"` = secondary bitmap.
- `len_type`: `0` = fixed length, `1/2/3` = LL/LLL/LLLL variable length prefix.
- `data_enc`: `"ascii"`, `"b"` (binary/BCD), `"cp500"` (EBCDIC), etc.
- Fields with `data_enc == "b"` are binary-encoded — do not populate from CSV strings.

---

## TCP framing

pyiso8583 handles message encoding only — TCP framing is manual.
Convention used in this project: **4-byte big-endian length prefix + data**.

```python
import struct

def send_frame(sock, data: bytes) -> None:
    sock.sendall(struct.pack(">I", len(data)) + data)

def recv_frame(sock) -> bytes | None:
    header = _recv_exact(sock, 4)
    if header is None:
        return None
    length = struct.unpack(">I", header)[0]
    return _recv_exact(sock, length)
```

---

## MTI convention

- Request: `0100` (authorization request)
- Response: set bit 1 of 3rd nibble → `0110`

```python
mti = req.get("t", "0100")
resp["t"] = mti[:2] + "1" + mti[3]
```

---

## Response codes (field 39)

| Code | Meaning |
|------|---------|
| `00` | Approved |
| `01` | Declined (refer to card issuer) |

Field 38 = authorization code (6-digit zero-padded string, only present on approval).

---

## Hex dump pattern

```python
def hex_dump(direction: str, length: int, data: bytes) -> None:
    hex_str = " ".join(f"{b:02x}" for b in data)
    log.info("%s Length: %d | %s", direction, length, hex_str)
```

Call after `recv_frame`: `hex_dump("RECV", len(data), data)`

---

## Key field numbers

| Field | Description |
|-------|-------------|
| `t`   | MTI |
| `p`   | Primary bitmap |
| `2`   | PAN (card number) |
| `3`   | Processing code |
| `4`   | Amount |
| `11`  | STAN (system trace audit number) — used to match request/response |
| `37`  | Retrieval reference number |
| `38`  | Authorization code (approval only) |
| `39`  | Response code |
| `41`  | Terminal ID |
| `42`  | Merchant ID |
| `49`  | Currency code |

---

## Usage

```
/iso8583
```

Invoke when working on ISO 8583 message encoding, decoding, spec definitions, or TCP framing.

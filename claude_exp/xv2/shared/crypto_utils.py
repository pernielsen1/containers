"""
MasterCard M/Chip cryptographic operations.

Key derivation follows EMV Book 2 Option A (single-DES on left/right halves with
complemented diversification data for the right half).

Session key derivation uses the ATC-based method from MasterCard M/Chip spec:
  SK_left  = 3DES(UDK, ATC || 0xF0 || 0x000000000000)
  SK_right = 3DES(UDK, ATC || 0x0F || 0x000000000000)

ARQC: ISO 9797-1 Algorithm 3 MAC (Retail MAC) over the ARQC input data.
ARPC: Method 1 — 3DES(SK_AC, ARQC XOR ARC) where ARC is 2-byte response code.
PIN:  ISO 9564-1 Format 0 PIN block decrypted with PEK.
CVV2: 3DES over PAN+expiry+service_code, decimal selection.
AAV:  HMAC-SHA1 over canonical f47 fields.
"""

import base64
import hashlib
import hmac
import json

from Crypto.Cipher import DES, DES3


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _tdes_encrypt(key_hex: str, data_hex: str) -> bytes:
    key = bytes.fromhex(key_hex)
    data = bytes.fromhex(data_hex)
    # pycryptodome requires 16 or 24-byte key; pad 16-byte to 24-byte (K1||K2||K1)
    if len(key) == 16:
        key = key + key[:8]
    cipher = DES3.new(key, DES3.MODE_ECB)
    return cipher.encrypt(data)


def _des_encrypt(key_bytes: bytes, data_bytes: bytes) -> bytes:
    cipher = DES.new(key_bytes, DES.MODE_ECB)
    return cipher.encrypt(data_bytes)


def _des_decrypt(key_bytes: bytes, data_bytes: bytes) -> bytes:
    cipher = DES.new(key_bytes, DES.MODE_ECB)
    return cipher.decrypt(data_bytes)


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# Key derivation
# ---------------------------------------------------------------------------

def derive_udk(imk_hex: str, pan: str, pan_seq: str) -> str:
    """Derive Unique Derived Key (UDK) from IMK using PAN and PAN sequence number.

    EMV Option A: diversification data = rightmost 12 PAN digits (excl check digit)
    + 2-digit PAN seq, zero-padded on the right to 8 bytes.
    """
    # rightmost 12 digits of PAN excluding check digit = PAN[:-1] last 12
    pan_no_check = pan[:-1]
    right12 = pan_no_check[-12:] if len(pan_no_check) >= 12 else pan_no_check.zfill(12)
    div_str = right12 + pan_seq  # 14 hex digits = 7 bytes
    # pad to 8 bytes with 0x0 nibble → append 'F' nybble and trailing zero
    div_str_padded = div_str + "0"  # 15 chars — need 16 for 8 bytes
    # Actually standard pads with 'F' then '0': result is 8 bytes (16 hex chars)
    div_hex = div_str_padded.ljust(16, "0")[:16]

    div_bytes = bytes.fromhex(div_hex)
    complement_bytes = bytes(b ^ 0xFF for b in div_bytes)
    complement_hex = complement_bytes.hex().upper()

    left = _tdes_encrypt(imk_hex, div_hex.upper())
    right = _tdes_encrypt(imk_hex, complement_hex)
    return (left + right).hex().upper()


def derive_session_key(udk_hex: str, atc_hex: str) -> str:
    """Derive AC session key from UDK using ATC.

    SK_left  = 3DES(UDK, ATC[2] || 0xF0 || 00 00 00 00 00 00)
    SK_right = 3DES(UDK, ATC[2] || 0x0F || 00 00 00 00 00 00)
    """
    atc = atc_hex.upper().zfill(4)  # 2 bytes = 4 hex chars
    left_input  = atc + "F0" + "00" * 5  # 8 bytes
    right_input = atc + "0F" + "00" * 5

    left  = _tdes_encrypt(udk_hex, left_input)
    right = _tdes_encrypt(udk_hex, right_input)
    return (left + right).hex().upper()


# ---------------------------------------------------------------------------
# ARQC / ARPC
# ---------------------------------------------------------------------------

def _retail_mac(key_hex: str, data_hex: str) -> bytes:
    """ISO 9797-1 Algorithm 3 Retail MAC (single DES left, 3DES final block)."""
    key = bytes.fromhex(key_hex)
    if len(key) == 24:
        k1, k2 = key[:8], key[8:16]
    else:
        k1, k2 = key[:8], key[8:16]

    data = bytes.fromhex(data_hex)
    # Pad with 80 00 ... to multiple of 8 bytes
    data += b"\x80"
    while len(data) % 8 != 0:
        data += b"\x00"

    # Single-DES CBC with K1 over all blocks except last
    register = b"\x00" * 8
    for i in range(0, len(data) - 8, 8):
        register = _des_encrypt(k1, _xor(register, data[i:i+8]))

    # Final block: 3DES with full key
    last_block = data[-8:]
    register = _xor(register, last_block)
    # decrypt with K2 then encrypt with K1
    register = _des_decrypt(k2, register)
    register = _des_encrypt(k1, register)
    return register


def _build_arqc_input(f55: dict) -> str:
    """Concatenate mandatory ARQC data elements from f55 into a hex string.

    Expects f55 fields (all hex strings):
      amount_auth (6 bytes), amount_other (6 bytes), terminal_country (2 bytes),
      terminal_verification_results (5 bytes), currency_code (2 bytes),
      transaction_date (3 bytes), transaction_type (1 byte),
      unpredictable_number (4 bytes), aip (2 bytes), atc (2 bytes)
    Missing fields are zero-filled to their standard length.
    """
    fields = [
        ("amount_auth",                   12),
        ("amount_other",                  12),
        ("terminal_country",               4),
        ("terminal_verification_results", 10),
        ("currency_code",                  4),
        ("transaction_date",               6),
        ("transaction_type",               2),
        ("unpredictable_number",           8),
        ("aip",                            4),
        ("atc",                            4),
    ]
    result = ""
    for name, width in fields:
        val = f55.get(name, "")
        result += val.upper().zfill(width)[:width]
    return result


def verify_arqc(pan: str, pan_seq: str, imk_hex: str, f55: dict) -> bool:
    """Return True if f55['cryptogram'] matches recomputed ARQC."""
    atc = f55.get("atc", "0001")
    udk = derive_udk(imk_hex, pan, pan_seq)
    sk  = derive_session_key(udk, atc)
    data_hex = _build_arqc_input(f55)
    expected = _retail_mac(sk, data_hex)
    received = bytes.fromhex(f55.get("cryptogram", ""))
    return hmac.compare_digest(expected, received)


def calculate_arpc_method1(arqc_hex: str, arc_hex: str, sk_hex: str) -> bytes:
    """ARPC Method 1: 3DES(SK_AC, ARQC XOR (ARC || 0x00 0x00 0x00 0x00 0x00 0x00))."""
    arqc = bytes.fromhex(arqc_hex)
    arc  = bytes.fromhex(arc_hex).ljust(8, b"\x00")  # pad ARC to 8 bytes
    xored = _xor(arqc, arc)
    return _tdes_encrypt(sk_hex, xored.hex().upper())


# ---------------------------------------------------------------------------
# PIN verification (ISO 9564-1 Format 0)
# ---------------------------------------------------------------------------

def verify_pin(pan: str, f52_b64: str, pek_hex: str, reference_pin: str) -> bool:
    """Decrypt ISO 9564-1 Format-0 PIN block and compare to reference_pin."""
    try:
        pin_block_enc = base64.b64decode(f52_b64)
        key = bytes.fromhex(pek_hex)
        if len(key) == 16:
            key = key + key[:8]
        cipher = DES3.new(key, DES3.MODE_ECB)
        pin_block = cipher.decrypt(pin_block_enc)

        # XOR with PAN block: 0000 + rightmost 12 PAN digits (excl check digit)
        pan_no_check = pan[:-1]
        right12 = pan_no_check[-12:].zfill(12)
        pan_block = bytes.fromhex("0000" + right12)

        decoded = _xor(pin_block, pan_block)
        # Format 0: nibble 0 = 0, nibble 1 = PIN length, nibbles 2..N = PIN digits
        fmt = (decoded[0] >> 4) & 0x0F
        if fmt != 0:
            return False
        pin_len = decoded[0] & 0x0F
        if not (4 <= pin_len <= 12):
            return False
        pin_digits = ""
        for i in range(pin_len):
            byte_idx = 1 + i // 2
            if i % 2 == 0:
                pin_digits += str((decoded[byte_idx] >> 4) & 0x0F)
            else:
                pin_digits += str(decoded[byte_idx] & 0x0F)
        return hmac.compare_digest(pin_digits, reference_pin)
    except Exception:
        return False


def encode_pin_block_format0(pin: str, pan: str) -> bytes:
    """Build and encrypt an ISO 9564-1 Format-0 PIN block — used in tests."""
    pin_len = len(pin)
    # PIN field: 0 | len | pin digits | F-padding
    pin_hex = "0" + str(pin_len) + pin + "F" * (14 - len(pin))
    pin_bytes = bytes.fromhex(pin_hex)
    pan_no_check = pan[:-1]
    right12 = pan_no_check[-12:].zfill(12)
    pan_block = bytes.fromhex("0000" + right12)
    return _xor(pin_bytes, pan_block)


def encrypt_pin_block(plain_pin_block: bytes, pek_hex: str) -> bytes:
    key = bytes.fromhex(pek_hex)
    if len(key) == 16:
        key = key + key[:8]
    cipher = DES3.new(key, DES3.MODE_ECB)
    return cipher.encrypt(plain_pin_block)


# ---------------------------------------------------------------------------
# CVV2 verification
# ---------------------------------------------------------------------------

_CVV2_SERVICE_CODE = "000"  # MasterCard CVV2 uses service code 000


def _compute_cvv(pan: str, expiry_mmyy: str, service_code: str, cvk_hex: str) -> str:
    """Compute CVV/CVV2 value per MasterCard algorithm."""
    # Concatenate PAN + expiry + service_code, right-pad with zeros to 32 digits
    data_str = pan + expiry_mmyy + service_code
    data_str = data_str.ljust(32, "0")[:32]

    left_hex  = data_str[:16]
    right_hex = data_str[16:]

    cvk = bytes.fromhex(cvk_hex)
    k1, k2 = cvk[:8], cvk[8:16]

    step1 = _des_encrypt(k1, bytes.fromhex(left_hex))
    step2 = _xor(step1, bytes.fromhex(right_hex))
    step3 = _des_encrypt(k1, step2)
    step4 = _des_decrypt(k2, step3)
    result = _des_encrypt(k1, step4)

    # Decimal digit extraction
    result_hex = result.hex()
    decimals = [c for c in result_hex if c.isdigit()]
    non_dec   = [str(int(c, 16) - 10) for c in result_hex if not c.isdigit()]
    cvv_str   = "".join(decimals + non_dec)
    return cvv_str[:3]


def verify_cvv2(pan: str, expiry_mmyy: str, cvv2: str, cvk_hex: str) -> bool:
    expected = _compute_cvv(pan, expiry_mmyy, _CVV2_SERVICE_CODE, cvk_hex)
    return hmac.compare_digest(expected, cvv2.zfill(3))


def compute_cvv2(pan: str, expiry_mmyy: str, cvk_hex: str) -> str:
    return _compute_cvv(pan, expiry_mmyy, _CVV2_SERVICE_CODE, cvk_hex)


# ---------------------------------------------------------------------------
# AAV verification (HMAC-SHA1)
# ---------------------------------------------------------------------------

def _canonical_aav_data(f47_data: dict) -> bytes:
    """Canonical byte string over f47 fields for HMAC: message_type+f14+pan."""
    parts = [
        f47_data.get("message_type", ""),
        f47_data.get("f14", ""),
    ]
    return "|".join(parts).encode("ascii")


def verify_aav(f47_data: dict, aav_key_hex: str, pan: str) -> bool:
    """Verify AAV field (base64) against HMAC-SHA1(aav_key, canonical_data || pan)."""
    try:
        key = bytes.fromhex(aav_key_hex)
        data = _canonical_aav_data(f47_data) + pan.encode("ascii")
        expected = hmac.new(key, data, hashlib.sha1).digest()
        received = base64.b64decode(f47_data.get("aav", ""))
        return hmac.compare_digest(expected, received)
    except Exception:
        return False


def compute_aav(f47_data: dict, aav_key_hex: str, pan: str) -> str:
    """Compute AAV for given f47 data — used in tests and test CSV generation."""
    key = bytes.fromhex(aav_key_hex)
    data = _canonical_aav_data(f47_data) + pan.encode("ascii")
    return base64.b64encode(hmac.new(key, data, hashlib.sha1).digest()).decode()

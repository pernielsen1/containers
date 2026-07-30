"""MasterCard M/Chip EMV operations. All functions are pure (no I/O)."""

import base64
import hashlib
import hmac

from Crypto.Cipher import DES, DES3

_MAC_FIELDS = (
    "amount_auth",
    "amount_other",
    "terminal_country",
    "terminal_verification_results",
    "currency_code",
    "transaction_date",
    "transaction_type",
    "unpredictable_number",
    "aip",
    "atc",
)


def derive_udk(imk_hex: str, pan: str, pan_seq: str) -> str:
    """EMV Option A UDK derivation."""
    imk = bytes.fromhex(imk_hex)
    pan_psn = (pan + pan_seq)[-16:].rjust(16, "0")
    z = bytes.fromhex(pan_psn)
    cipher = DES3.new(imk, DES3.MODE_ECB)
    udk_a = cipher.encrypt(z)
    z_complement = bytes(b ^ 0xFF for b in z)
    udk_b = cipher.encrypt(z_complement)
    return (udk_a + udk_b).hex().upper()


def derive_session_key(udk_hex: str, atc_hex: str) -> str:
    """ATC-based session key (EMV Common Session Key Derivation, Option A)."""
    udk = bytes.fromhex(udk_hex)
    cipher = DES3.new(udk, DES3.MODE_ECB)
    atc = bytes.fromhex(atc_hex.zfill(4))[:2]
    r_left = atc + b"\xf0" + b"\x00" * 5
    r_right = atc + b"\x0f" + b"\x00" * 5
    sk_left = cipher.encrypt(r_left)
    sk_right = cipher.encrypt(r_right)
    return (sk_left + sk_right).hex().upper()


def _pad_iso9797_2(data: bytes) -> bytes:
    padded = data + b"\x80"
    while len(padded) % 8 != 0:
        padded += b"\x00"
    return padded


def _retail_mac(key16: bytes, data: bytes) -> bytes:
    """ISO/IEC 9797-1 MAC Algorithm 3 (Retail MAC)."""
    k1, k2 = key16[:8], key16[8:16]
    des_k1 = DES.new(k1, DES.MODE_ECB)
    des_k2 = DES.new(k2, DES.MODE_ECB)
    h = b"\x00" * 8
    for i in range(0, len(data), 8):
        block = data[i : i + 8]
        x = bytes(a ^ b for a, b in zip(block, h))
        h = des_k1.encrypt(x)
    return des_k1.encrypt(des_k2.decrypt(h))


def _build_mac_input(f55: dict) -> bytes:
    data = b""
    for key in _MAC_FIELDS:
        data += bytes.fromhex(f55[key])
    return data


def verify_arqc(pan: str, pan_seq: str, imk_hex: str, f55: dict) -> bool:
    """Retail MAC ARQC check."""
    udk = derive_udk(imk_hex, pan, pan_seq)
    sk = derive_session_key(udk, f55["atc"])
    data = _pad_iso9797_2(_build_mac_input(f55))
    mac = _retail_mac(bytes.fromhex(sk), data)
    return mac.hex().upper() == f55.get("cryptogram", "").upper()


def calculate_arpc_method1(arqc_hex: str, arc_hex: str, sk_hex: str) -> bytes:
    """ARPC Method 1: encrypt(ARQC XOR (ARC padded to 8 bytes)) with the session key."""
    arqc = bytearray(bytes.fromhex(arqc_hex))
    arc = bytes.fromhex(arc_hex.zfill(4))
    for i in range(min(len(arc), len(arqc))):
        arqc[i] ^= arc[i]
    cipher = DES3.new(bytes.fromhex(sk_hex), DES3.MODE_ECB)
    return cipher.encrypt(bytes(arqc))


def _pan_block(pan: str) -> bytes:
    digits = pan[:-1][-12:].rjust(12, "0")
    return bytes.fromhex("0000" + digits)


def encode_pin_block_format0(pin: str, pan: str) -> bytes:
    """Build cleartext ISO 9564-1 Format-0 PIN block (tests)."""
    control = "0"
    length_nibble = format(len(pin), "X")
    pin_field = (control + length_nibble + pin).ljust(16, "F")
    pin_block = bytes.fromhex(pin_field)
    pan_block = _pan_block(pan)
    return bytes(a ^ b for a, b in zip(pin_block, pan_block))


def encrypt_pin_block(plain: bytes, pek_hex: str) -> bytes:
    """3DES encrypt PIN block."""
    cipher = DES3.new(bytes.fromhex(pek_hex), DES3.MODE_ECB)
    return cipher.encrypt(plain)


def verify_pin(pan: str, f52_b64: str, pek_hex: str, reference_pin: str) -> bool:
    """ISO 9564-1 Format-0 PIN block verification."""
    try:
        encrypted = base64.b64decode(f52_b64)
    except Exception:
        return False
    cipher = DES3.new(bytes.fromhex(pek_hex), DES3.MODE_ECB)
    clear_block = cipher.decrypt(encrypted)
    pan_block = _pan_block(pan)
    pin_block = bytes(a ^ b for a, b in zip(clear_block, pan_block))
    hexstr = pin_block.hex().upper()
    pin_len = int(hexstr[1], 16)
    pin_digits = hexstr[2 : 2 + pin_len]
    return pin_digits == reference_pin


def _cvv_data_blocks(pan: str, expiry_mmyy: str, service_code: str) -> tuple:
    mm, yy = expiry_mmyy[:2], expiry_mmyy[2:]
    expiry_yymm = yy + mm
    data = (pan + expiry_yymm + service_code).ljust(32, "0")[:32]
    return bytes.fromhex(data[:16]), bytes.fromhex(data[16:32])


def _cvv_core(pan: str, expiry_mmyy: str, cvk_hex: str, service_code: str = "000") -> str:
    cvk = bytes.fromhex(cvk_hex)
    cvk_a, cvk_b = cvk[:8], cvk[8:16]
    block_a, block_b = _cvv_data_blocks(pan, expiry_mmyy, service_code)
    des_a = DES.new(cvk_a, DES.MODE_ECB)
    des_b = DES.new(cvk_b, DES.MODE_ECB)
    r1 = des_a.encrypt(block_a)
    r2 = bytes(a ^ b for a, b in zip(r1, block_b))
    r3 = des_a.encrypt(r2)
    r4 = des_b.decrypt(r3)
    r5 = des_a.encrypt(r4)
    hexdigits = r5.hex()
    decimals = [c for c in hexdigits if c.isdigit()]
    if len(decimals) < 3:
        decimals += [str((int(c, 16) - 10) % 10) for c in hexdigits if c.upper() in "ABCDEF"]
    return "".join(decimals[:3])


def compute_cvv2(pan: str, expiry_mmyy: str, cvk_hex: str) -> str:
    """Compute CVV2 (tests)."""
    return _cvv_core(pan, expiry_mmyy, cvk_hex)


def verify_cvv2(pan: str, expiry_mmyy: str, cvv2: str, cvk_hex: str) -> bool:
    """MasterCard CVV2 verification."""
    return compute_cvv2(pan, expiry_mmyy, cvk_hex) == cvv2


def compute_aav(f47_data: dict, aav_key_hex: str, pan: str) -> str:
    """Compute AAV (tests)."""
    key = bytes.fromhex(aav_key_hex)
    message = (pan + f47_data.get("f14", "") + f47_data.get("message_type", "")).encode("ascii")
    mac = hmac.new(key, message, hashlib.sha1).digest()
    return base64.b64encode(mac).decode("ascii")


def verify_aav(f47_data: dict, aav_key_hex: str, pan: str) -> bool:
    """HMAC-SHA1 AAV verification."""
    return f47_data.get("aav", "") == compute_aav(f47_data, aav_key_hex, pan)

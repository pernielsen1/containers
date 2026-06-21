"""MasterCard M/Chip EMV operations. All functions are pure (no I/O)."""

import base64
import hashlib
import hmac

from Crypto.Cipher import DES, DES3


def _account_number_field(pan: str) -> str:
    # ISO 9564-1 Format 0: 0000 + rightmost 12 digits of the PAN, excluding the check digit
    digits = pan[:-1]
    account = digits[-12:] if len(digits) >= 12 else digits.zfill(12)
    return "0000" + account


def _retail_mac(key16: bytes, data: bytes) -> bytes:
    # ISO 9797-1 MAC Algorithm 3 / ANSI X9.19 Retail MAC
    k1, k2 = key16[:8], key16[8:16]
    padded = data + b"\x80"
    while len(padded) % 8 != 0:
        padded += b"\x00"

    cipher1 = DES.new(k1, DES.MODE_CBC, b"\x00" * 8)
    encrypted = cipher1.encrypt(padded)
    last_block = encrypted[-8:]

    decrypted = DES.new(k2, DES.MODE_ECB).decrypt(last_block)
    return DES.new(k1, DES.MODE_ECB).encrypt(decrypted)


def derive_udk(imk_hex: str, pan: str, pan_seq: str) -> str:
    """EMV Option A UDK derivation."""
    z = (pan + pan_seq)[-16:].zfill(16)
    zr = bytes.fromhex(z)
    zl = bytes(b ^ 0xFF for b in zr)

    cipher = DES3.new(bytes.fromhex(imk_hex), DES3.MODE_ECB)
    kl = cipher.encrypt(zl)
    kr = cipher.encrypt(zr)
    return (kl + kr).hex().upper()


def derive_session_key(udk_hex: str, atc_hex: str) -> str:
    """ATC-based session key."""
    atc = bytes.fromhex(atc_hex.zfill(4))
    left_input = atc + b"\xf0" + b"\x00" * 5
    right_input = atc + b"\x0f" + b"\x00" * 5

    cipher = DES3.new(bytes.fromhex(udk_hex), DES3.MODE_ECB)
    skl = cipher.encrypt(left_input)
    skr = cipher.encrypt(right_input)
    return (skl + skr).hex().upper()


def verify_arqc(pan: str, pan_seq: str, imk_hex: str, f55: dict) -> bool:
    """Retail MAC ARQC check."""
    udk = derive_udk(imk_hex, pan, pan_seq)
    sk = derive_session_key(udk, f55["atc"])

    mac_input = bytes.fromhex(
        f55["amount_auth"]
        + f55["amount_other"]
        + f55["terminal_country"]
        + f55["terminal_verification_results"]
        + f55["currency_code"]
        + f55["transaction_date"]
        + f55["transaction_type"]
        + f55["unpredictable_number"]
        + f55["aip"]
        + f55["atc"]
    )
    mac = _retail_mac(bytes.fromhex(sk), mac_input)
    return mac.hex().upper() == f55["cryptogram"].upper()


def calculate_arpc_method1(arqc_hex: str, arc_hex: str, sk_hex: str) -> bytes:
    """ARPC Method 1."""
    arqc = bytes.fromhex(arqc_hex)
    arc = bytes.fromhex(arc_hex).rjust(2, b"\x00")[-2:]
    padded_arc = arc + b"\x00" * 6

    xor_data = bytes(a ^ b for a, b in zip(arqc, padded_arc))
    cipher = DES3.new(bytes.fromhex(sk_hex), DES3.MODE_ECB)
    return cipher.encrypt(xor_data)


def encode_pin_block_format0(pin: str, pan: str) -> bytes:
    """Build cleartext PIN block (tests)."""
    pin_field_hex = "0" + format(len(pin), "x") + pin + "F" * (14 - len(pin))
    pin_field = bytes.fromhex(pin_field_hex)
    pan_field = bytes.fromhex(_account_number_field(pan))
    return bytes(a ^ b for a, b in zip(pin_field, pan_field))


def encrypt_pin_block(plain: bytes, pek_hex: str) -> bytes:
    """3DES encrypt PIN block."""
    cipher = DES3.new(bytes.fromhex(pek_hex), DES3.MODE_ECB)
    return cipher.encrypt(plain)


def verify_pin(pan: str, f52_b64: str, pek_hex: str, reference_pin: str) -> bool:
    """ISO 9564-1 Format-0."""
    encrypted = base64.b64decode(f52_b64)
    cipher = DES3.new(bytes.fromhex(pek_hex), DES3.MODE_ECB)
    plain = cipher.decrypt(encrypted)

    pan_field = bytes.fromhex(_account_number_field(pan))
    pin_field = bytes(a ^ b for a, b in zip(plain, pan_field))
    hex_str = pin_field.hex()

    if hex_str[0] != "0":
        return False
    pin_len = int(hex_str[1], 16)
    extracted_pin = hex_str[2 : 2 + pin_len]
    return extracted_pin == reference_pin


def compute_cvv2(pan: str, expiry_mmyy: str, cvk_hex: str) -> str:
    """Compute CVV2 (tests)."""
    cvk = bytes.fromhex(cvk_hex)
    cvk_a, cvk_b = cvk[:8], cvk[8:16]

    data1 = bytes.fromhex(pan.ljust(16, "0")[:16])
    yymm = expiry_mmyy[2:4] + expiry_mmyy[0:2]
    data2 = bytes.fromhex((yymm + "000").ljust(16, "0")[:16])

    step1 = DES.new(cvk_a, DES.MODE_ECB).encrypt(data1)
    step2 = bytes(a ^ b for a, b in zip(step1, data2))
    step3 = DES3.new(cvk, DES3.MODE_ECB).encrypt(step2)

    hex_digits = step3.hex()
    decimal_digits = [c for c in hex_digits if c.isdigit()]
    converted_letters = [str(int(c, 16) - 10) for c in hex_digits if not c.isdigit()]
    return "".join(decimal_digits + converted_letters)[:3]


def verify_cvv2(pan: str, expiry_mmyy: str, cvv2: str, cvk_hex: str) -> bool:
    """MasterCard CVV2."""
    return compute_cvv2(pan, expiry_mmyy, cvk_hex) == cvv2


def _aav_message(f47_data: dict, pan: str) -> bytes:
    atc = f47_data.get("f55", {}).get("atc", "")
    message_type = f47_data.get("message_type", "")
    return f"{pan}|{message_type}|{atc}".encode("ascii")


def compute_aav(f47_data: dict, aav_key_hex: str, pan: str) -> str:
    """Compute AAV (tests)."""
    digest = hmac.new(bytes.fromhex(aav_key_hex), _aav_message(f47_data, pan), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def verify_aav(f47_data: dict, aav_key_hex: str, pan: str) -> bool:
    """HMAC-SHA1 AAV."""
    return compute_aav(f47_data, aav_key_hex, pan) == f47_data.get("aav")

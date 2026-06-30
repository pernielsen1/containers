import hashlib
import hmac
import struct
import base64

from Crypto.Cipher import DES3, DES
from Crypto.Hash import CMAC


def _adjust_parity(key_bytes: bytes) -> bytes:
    result = []
    for b in key_bytes:
        bits = bin(b).count("1")
        if bits % 2 == 0:
            b ^= 1
        result.append(b)
    return bytes(result)


def _des3_encrypt(key_hex: str, data: bytes) -> bytes:
    key = bytes.fromhex(key_hex)
    cipher = DES3.new(key, DES3.MODE_ECB)
    return cipher.encrypt(data)


def _des3_decrypt(key_hex: str, data: bytes) -> bytes:
    key = bytes.fromhex(key_hex)
    cipher = DES3.new(key, DES3.MODE_ECB)
    return cipher.decrypt(data)


def derive_udk(imk_hex: str, pan: str, pan_seq: str) -> str:
    # EMV Option A: derive UDK from IMK using PAN + PAN sequence number
    pan_data = (pan + pan_seq).ljust(16, "0")[-16:]
    # Use last 16 digits of PAN + PAN seq, padded
    data = bytes.fromhex(pan_data.ljust(16, "0")[:16])

    left = _des3_encrypt(imk_hex, data)
    # Complement of data
    comp_data = bytes([b ^ 0xFF for b in data])
    right = _des3_encrypt(imk_hex, comp_data)
    udk = left + right
    return udk.hex().upper()


def derive_session_key(udk_hex: str, atc_hex: str) -> str:
    atc = bytes.fromhex(atc_hex)
    # Diversification data: ATC || 0x0000 || 0x00 || 0x00 || 0x00 || 0x00 || 0x00 || 0x00
    # Left: F0 || ATC || 00 00 00 00 00 00
    # Right: 0F || ATC || 00 00 00 00 00 00
    div_left = b"\xf0" + atc + b"\x00" * 5
    div_right = b"\x0f" + atc + b"\x00" * 5
    left = _des3_encrypt(udk_hex, div_left)
    right = _des3_encrypt(udk_hex, div_right)
    return (left + right).hex().upper()


def _retail_mac(key_hex: str, data: bytes) -> bytes:
    key = bytes.fromhex(key_hex)
    k1 = key[:8]
    k2 = key[8:16]
    # Pad to 8-byte boundary
    pad_len = (8 - len(data) % 8) % 8
    if pad_len == 0:
        pad_len = 0
    padded = data + b"\x00" * pad_len

    result = b"\x00" * 8
    for i in range(0, len(padded), 8):
        block = padded[i:i+8]
        result = bytes([r ^ b for r, b in zip(result, block)])
        if i < len(padded) - 8:
            cipher = DES.new(k1, DES.MODE_ECB)
            result = cipher.encrypt(result)

    cipher = DES.new(k1, DES.MODE_ECB)
    result = cipher.encrypt(result)

    decipher = DES.new(k2, DES.MODE_ECB)
    result = decipher.decrypt(result)

    cipher = DES.new(k1, DES.MODE_ECB)
    result = cipher.encrypt(result)

    return result


def verify_arqc(pan: str, pan_seq: str, imk_hex: str, f55: dict) -> bool:
    try:
        udk_hex = derive_udk(imk_hex, pan, pan_seq)
        atc_hex = f55["atc"]
        sk_hex = derive_session_key(udk_hex, atc_hex)

        # Build ARQC input data
        fields = [
            f55.get("amount_auth", "000000000000"),
            f55.get("amount_other", "000000000000"),
            f55.get("terminal_country", "0000"),
            f55.get("terminal_verification_results", "0000000000"),
            f55.get("currency_code", "0000"),
            f55.get("transaction_date", "000000"),
            f55.get("transaction_type", "00"),
            f55.get("unpredictable_number", "00000000"),
            f55.get("aip", "0000"),
            atc_hex,
            f55.get("iad", ""),
        ]
        data = b"".join(bytes.fromhex(x) for x in fields if x)

        computed = _retail_mac(sk_hex, data)
        expected = bytes.fromhex(f55["cryptogram"])
        return computed == expected
    except Exception:
        return False


def calculate_arpc_method1(arqc_hex: str, arc_hex: str, sk_hex: str) -> bytes:
    arqc = bytes.fromhex(arqc_hex)
    arc = bytes.fromhex(arc_hex)
    arc_padded = arc + b"\x00" * (8 - len(arc))
    xored = bytes([a ^ b for a, b in zip(arqc, arc_padded)])
    return _des3_encrypt(sk_hex, xored)


def verify_pin(pan: str, f52_b64: str, pek_hex: str, reference_pin: str) -> bool:
    try:
        encrypted = base64.b64decode(f52_b64)
        cleartext = _des3_decrypt(pek_hex, encrypted)
        decoded_pin = _decode_pin_block_format0(cleartext, pan)
        return decoded_pin == reference_pin
    except Exception:
        return False


def _decode_pin_block_format0(pin_block: bytes, pan: str) -> str:
    # XOR with PAN block: 0000 + rightmost 12 digits of PAN excluding check digit
    pan_block = bytes.fromhex("0000" + pan[-13:-1])
    decoded = bytes([a ^ b for a, b in zip(pin_block, pan_block)])
    pin_len = decoded[0] & 0x0F
    pin_digits = ""
    for i in range(1, (pin_len + 1) // 2 + 1):
        b = decoded[i]
        pin_digits += str((b >> 4) & 0x0F)
        if len(pin_digits) < pin_len:
            pin_digits += str(b & 0x0F)
    return pin_digits[:pin_len]


def encode_pin_block_format0(pin: str, pan: str) -> bytes:
    pin_len = len(pin)
    pin_str = f"0{pin_len}{pin}".ljust(16, "F")
    pin_block = bytes.fromhex(pin_str)
    pan_block = bytes.fromhex("0000" + pan[-13:-1])
    return bytes([a ^ b for a, b in zip(pin_block, pan_block)])


def encrypt_pin_block(plain: bytes, pek_hex: str) -> bytes:
    return _des3_encrypt(pek_hex, plain)


def verify_cvv2(pan: str, expiry_mmyy: str, cvv2: str, cvk_hex: str) -> bool:
    try:
        computed = compute_cvv2(pan, expiry_mmyy, cvk_hex)
        return computed == cvv2
    except Exception:
        return False


def compute_cvv2(pan: str, expiry_mmyy: str, cvk_hex: str) -> str:
    # CVV2: DES3(CVK, PAN||expiry||service_code_000) XOR last block
    service_code = "000"
    data_str = (pan + expiry_mmyy + service_code).ljust(32, "0")[:32]
    data = bytes.fromhex(data_str)

    key = bytes.fromhex(cvk_hex)
    k1 = key[:8]
    k2 = key[8:16]

    cipher1 = DES.new(k1, DES.MODE_ECB)
    block1 = cipher1.encrypt(data[:8])

    xored = bytes([a ^ b for a, b in zip(block1, data[8:])])
    cipher2 = DES.new(k1, DES.MODE_ECB)
    step2 = cipher2.encrypt(xored)

    decipher = DES.new(k2, DES.MODE_ECB)
    step3 = decipher.decrypt(step2)

    cipher3 = DES.new(k1, DES.MODE_ECB)
    result = cipher3.encrypt(step3)

    digits = ""
    for b in result:
        high = (b >> 4) & 0x0F
        low = b & 0x0F
        if high <= 9:
            digits += str(high)
        if low <= 9:
            digits += str(low)
    for b in result:
        high = (b >> 4) & 0x0F
        low = b & 0x0F
        if high > 9:
            digits += str(high - 10)
        if low > 9:
            digits += str(low - 10)

    return digits[:3]


def verify_aav(f47_data: dict, aav_key_hex: str, pan: str) -> bool:
    try:
        aav_b64 = f47_data.get("aav", "")
        expected = base64.b64decode(aav_b64)
        computed_hex = compute_aav(f47_data, aav_key_hex, pan)
        computed = bytes.fromhex(computed_hex)
        return computed == expected
    except Exception:
        return False


def compute_aav(f47_data: dict, aav_key_hex: str, pan: str) -> str:
    key = bytes.fromhex(aav_key_hex)
    # Build AAV input: PAN + selected f47 fields
    msg = pan.encode()
    for field in ("f14", "cvv2"):
        v = f47_data.get(field, "")
        if v:
            msg += v.encode()
    mac = hmac.new(key, msg, hashlib.sha1).digest()
    return mac.hex()

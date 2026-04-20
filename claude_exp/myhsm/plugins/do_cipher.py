"""CBC encryption plugin. Input dict keys: key_token, algorithm, data (base64), iv (hex, optional)."""

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import keystore

from Crypto.Cipher import AES, DES
from Crypto.Util.Padding import pad

BLOCK_SIZES = {"DES": 8, "AES": 16}


def run(input_data: dict) -> dict:
    key_token = input_data.get("key_token")
    algorithm = (input_data.get("algorithm") or "").upper()
    data_b64 = input_data.get("data")
    iv_hex = input_data.get("iv")

    if not key_token:
        return {"result_bool": False, "error": "key_token is required"}
    if algorithm not in BLOCK_SIZES:
        return {"result_bool": False, "error": f"algorithm must be DES or AES, got '{algorithm}'"}
    if not data_b64:
        return {"result_bool": False, "error": "data is required"}

    key_bytes = keystore.get(key_token)
    if key_bytes is None:
        return {"result_bool": False, "error": f"key token '{key_token}' not found in keystore"}

    block_size = BLOCK_SIZES[algorithm]
    if iv_hex:
        iv = bytes.fromhex(iv_hex)
    else:
        iv = bytes(block_size)

    try:
        plaintext = base64.b64decode(data_b64)
        padded = pad(plaintext, block_size)
        if algorithm == "DES":
            cipher = DES.new(key_bytes, DES.MODE_CBC, iv)
        else:
            cipher = AES.new(key_bytes, AES.MODE_CBC, iv)
        encrypted = cipher.encrypt(padded)
        return {"result_bool": True, "result_data": base64.b64encode(encrypted).decode()}
    except Exception as exc:
        return {"result_bool": False, "error": str(exc)}

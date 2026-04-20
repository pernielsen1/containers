"""PIN block re-encryption (translation) plugin.

Decrypts a PIN block under the incoming key and re-encrypts it under the outgoing key.
Supports DES (8-byte key) and 3DES/TDES (16- or 24-byte key) in CBC mode.

Input dict keys:
  in_key_token   : keystore token for the incoming encryption key
  out_key_token  : keystore token for the outgoing encryption key
  data           : base64-encoded encrypted PIN block
  iv             : optional hex IV (defaults to 8 zero bytes)
"""

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import keystore

from Crypto.Cipher import DES, DES3

DES_BLOCK = 8


def _cipher(key_bytes: bytes, iv: bytes):
    if len(key_bytes) == 8:
        return DES.new(key_bytes, DES.MODE_CBC, iv)
    return DES3.new(key_bytes, DES3.MODE_CBC, iv)


def run(input_data: dict) -> dict:
    in_token  = input_data.get("in_key_token")
    out_token = input_data.get("out_key_token")
    data_b64  = input_data.get("data")
    iv_hex    = input_data.get("iv")

    if not in_token or not out_token or not data_b64:
        return {"result_bool": False, "error": "in_key_token, out_key_token, and data are required"}

    in_key  = keystore.get(in_token)
    out_key = keystore.get(out_token)
    if in_key is None:
        return {"result_bool": False, "error": f"key '{in_token}' not found in keystore"}
    if out_key is None:
        return {"result_bool": False, "error": f"key '{out_token}' not found in keystore"}

    iv = bytes.fromhex(iv_hex) if iv_hex else bytes(DES_BLOCK)

    try:
        encrypted_in = base64.b64decode(data_b64)
        plain        = _cipher(in_key, iv).decrypt(encrypted_in)
        encrypted_out = _cipher(out_key, iv).encrypt(plain)
        return {"result_bool": True, "result_data": base64.b64encode(encrypted_out).decode()}
    except Exception as exc:
        return {"result_bool": False, "error": str(exc)}

#!/usr/bin/env python3
import sys
import urllib.request
import json
import base64

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5000"
INPUT = sys.argv[2] if len(sys.argv) > 2 else "hello world"
USERNAME, PASSWORD = "admin", "admin123"


def post(path, body=None, token=None):
    url = BASE_URL + path
    data = json.dumps(body).encode() if body is not None else b""
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    else:
        creds = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


print("--- Login ---")
auth = post("/sys/v1/session/auth")
token = auth["access_token"]
print(f"Token: {token}")

print("\n--- Invoke upper_case plugin ---")
result = post("/crypto/v1/plugins/upper_case", {"input": INPUT}, token=token)
print(json.dumps(result, indent=2))

print("\n--- lower_case: normal input ---")
result = post("/crypto/v1/plugins/lower_case", {"input": "HELLO WORLD"}, token=token)
print(json.dumps(result, indent=2))

print("\n--- lower_case: error case (42_IS_UPPER_CASE) ---")
result = post("/crypto/v1/plugins/lower_case", {"input": "42_IS_UPPER_CASE"}, token=token)
print(json.dumps(result, indent=2))

plaintext_b64 = base64.b64encode(b"Hello World!!!!").decode()  # 15 bytes -> padded to 16

print("\n--- do_cipher: AES-128 with des_key (wrong size, expect error) ---")
result = post("/crypto/v1/plugins/do_cipher", {
    "key_token": "des_key", "algorithm": "AES", "data": plaintext_b64
}, token=token)
print(json.dumps(result, indent=2))

print("\n--- do_cipher: DES with des_key ---")
result = post("/crypto/v1/plugins/do_cipher", {
    "key_token": "des_key", "algorithm": "DES", "data": plaintext_b64
}, token=token)
print(json.dumps(result, indent=2))

print("\n--- do_cipher: AES-128 with aes128_key ---")
result = post("/crypto/v1/plugins/do_cipher", {
    "key_token": "aes128_key", "algorithm": "AES", "data": plaintext_b64
}, token=token)
print(json.dumps(result, indent=2))

print("\n--- do_cipher: AES-256 with aes256_key, custom IV ---")
result = post("/crypto/v1/plugins/do_cipher", {
    "key_token": "aes256_key", "algorithm": "AES", "data": plaintext_b64,
    "iv": "0f0e0d0c0b0a09080706050403020100"
}, token=token)
print(json.dumps(result, indent=2))

print("\n--- derive_key: diversify des_key ---")
result = post("/crypto/v1/keys/derive", {"keyname": "des_key", "diversify": "deadbeef01020304"}, token=token)
print(json.dumps(result, indent=2))
derived_token = result.get("token_id")

print("\n--- do_cipher: DES with derived key ---")
result = post("/crypto/v1/plugins/do_cipher", {
    "key_token": derived_token, "algorithm": "DES", "data": plaintext_b64
}, token=token)
print(json.dumps(result, indent=2))

# ---------------------------------------------------------------------------
# ISO 8583 field 52 — PIN block translation
# PAN=555551234567890, PIN=1234
# ISO 9564 Format 0:
#   PIN field : 041234FFFFFFFFFF
#   PAN field : 0000555123456789   (0000 + rightmost 12 PAN digits excl. check)
#   Plain PB  : 041261AEDCBA9876   (XOR of the two)
#   Encrypted under des_key (DES CBC, IV=0): 2B265B07B72D9DB7
# Translation target: des_key_out  (C1C1C1C1C1C1C1C1 1C1C1C1C1C1C1C1C, 3DES)
# ---------------------------------------------------------------------------

from Crypto.Cipher import DES, DES3

def iso9564_f0(pan: str, pin: str) -> bytes:
    pin_field = f"0{len(pin)}{pin}" + "F" * (14 - len(pin))
    pan_field  = "0000" + pan[:-1][-12:]   # drop check digit, take rightmost 12
    return bytes(a ^ b for a, b in zip(bytes.fromhex(pin_field), bytes.fromhex(pan_field)))

plain_pb = iso9564_f0("555551234567890", "1234")
print(f"\n--- PIN block setup ---")
print(f"Plain PIN block (hex): {plain_pb.hex().upper()}")

des_key = bytes.fromhex("0102030405060708")
incoming_enc = DES.new(des_key, DES.MODE_CBC, bytes(8)).encrypt(plain_pb)
incoming_b64 = base64.b64encode(incoming_enc).decode()
print(f"Incoming encrypted PIN block (b64): {incoming_b64}")

print("\n--- pin_translate: des_key -> des_key_out ---")
result = post("/crypto/v1/plugins/pin_translate", {
    "in_key_token":  "des_key",
    "out_key_token": "des_key_out",
    "data": incoming_b64,
}, token=token)
print(json.dumps(result, indent=2))

# Verify: decrypt the translated block with des_key_out and check it matches plain_pb
if result.get("result_bool"):
    des_key_out = bytes.fromhex("C1C1C1C1C1C1C1C11C1C1C1C1C1C1C1C")
    translated_enc = base64.b64decode(result["result_data"])
    decrypted_pb = DES3.new(des_key_out, DES3.MODE_CBC, bytes(8)).decrypt(translated_enc)
    match = decrypted_pb == plain_pb
    print(f"Verification — decrypted plain PIN block matches original: {match}")
    print(f"  Expected : {plain_pb.hex().upper()}")
    print(f"  Got      : {decrypted_pb.hex().upper()}")

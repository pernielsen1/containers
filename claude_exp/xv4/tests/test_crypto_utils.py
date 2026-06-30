import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from shared.crypto_utils import (
    calculate_arpc_method1,
    compute_aav,
    compute_cvv2,
    derive_session_key,
    derive_udk,
    encode_pin_block_format0,
    encrypt_pin_block,
    verify_aav,
    verify_arqc,
    verify_cvv2,
    verify_pin,
)

PANS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pans_defined.json")
with open(PANS_PATH) as f:
    PANS = json.load(f)

PAN = "4111111111111111"
PAN_DATA = PANS[PAN]


def test_derive_udk():
    udk = derive_udk(PAN_DATA["imk_ac"], PAN, PAN_DATA["pan_seq"])
    assert len(udk) == 32
    assert udk == udk.upper()


def test_derive_session_key():
    udk = derive_udk(PAN_DATA["imk_ac"], PAN, PAN_DATA["pan_seq"])
    sk = derive_session_key(udk, "0001")
    assert len(sk) == 32


def test_pin_roundtrip():
    pin = PAN_DATA["pin"]
    plain = encode_pin_block_format0(pin, PAN)
    encrypted = encrypt_pin_block(plain, PAN_DATA["pek"])
    b64 = base64.b64encode(encrypted).decode()
    assert verify_pin(PAN, b64, PAN_DATA["pek"], pin)


def test_pin_wrong():
    pin = PAN_DATA["pin"]
    plain = encode_pin_block_format0("9999", PAN)
    encrypted = encrypt_pin_block(plain, PAN_DATA["pek"])
    b64 = base64.b64encode(encrypted).decode()
    assert not verify_pin(PAN, b64, PAN_DATA["pek"], pin)


def test_cvv2_roundtrip():
    expiry = "1225"
    cvv2 = compute_cvv2(PAN, expiry, PAN_DATA["cvk"])
    assert len(cvv2) == 3
    assert verify_cvv2(PAN, expiry, cvv2, PAN_DATA["cvk"])


def test_cvv2_wrong():
    expiry = "1225"
    assert not verify_cvv2(PAN, expiry, "999", PAN_DATA["cvk"])


def test_aav_roundtrip():
    f47_data = {"f14": "1225", "cvv2": "123"}
    aav_hex = compute_aav(f47_data, PAN_DATA["aav_key"], PAN)
    f47_data["aav"] = base64.b64encode(bytes.fromhex(aav_hex)).decode()
    assert verify_aav(f47_data, PAN_DATA["aav_key"], PAN)


def test_aav_wrong():
    f47_data = {"f14": "1225", "cvv2": "123", "aav": base64.b64encode(b"\x00" * 20).decode()}
    assert not verify_aav(f47_data, PAN_DATA["aav_key"], PAN)


def test_arpc_method1():
    udk = derive_udk(PAN_DATA["imk_ac"], PAN, PAN_DATA["pan_seq"])
    sk = derive_session_key(udk, "0001")
    arqc_bytes = bytes.fromhex("AABBCCDDEEFF0011")
    arc_hex = "3030"
    arpc = calculate_arpc_method1(arqc_bytes.hex(), arc_hex, sk)
    assert len(arpc) == 8

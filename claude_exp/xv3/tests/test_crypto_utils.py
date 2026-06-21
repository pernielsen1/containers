import base64
import json

import pytest

from shared import crypto_utils as cu

with open("pans_defined.json") as f:
    PANS = json.load(f)

PAN = "4111111111111111"
KEYS = PANS[PAN]


def test_derive_udk_deterministic_and_correct_length():
    udk1 = cu.derive_udk(KEYS["imk_ac"], PAN, KEYS["pan_seq"])
    udk2 = cu.derive_udk(KEYS["imk_ac"], PAN, KEYS["pan_seq"])
    assert udk1 == udk2
    assert len(bytes.fromhex(udk1)) == 16


def test_derive_session_key_changes_with_atc():
    udk = cu.derive_udk(KEYS["imk_ac"], PAN, KEYS["pan_seq"])
    sk1 = cu.derive_session_key(udk, "0001")
    sk2 = cu.derive_session_key(udk, "0002")
    assert sk1 != sk2
    assert len(bytes.fromhex(sk1)) == 16


def test_verify_arqc_roundtrip():
    udk = cu.derive_udk(KEYS["imk_ac"], PAN, KEYS["pan_seq"])
    atc = "0001"
    sk = cu.derive_session_key(udk, atc)

    f55 = {
        "amount_auth": "000000001000",
        "amount_other": "000000000000",
        "terminal_country": "0208",
        "terminal_verification_results": "8480048000",
        "currency_code": "0978",
        "transaction_date": "260530",
        "transaction_type": "00",
        "unpredictable_number": "A1B2C3D4",
        "aip": "1800",
        "atc": atc,
    }
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
    arqc = cu._retail_mac(bytes.fromhex(sk), mac_input)
    f55["cryptogram"] = arqc.hex().upper()

    assert cu.verify_arqc(PAN, KEYS["pan_seq"], KEYS["imk_ac"], f55) is True

    f55_bad = dict(f55)
    f55_bad["cryptogram"] = "00" * 8
    assert cu.verify_arqc(PAN, KEYS["pan_seq"], KEYS["imk_ac"], f55_bad) is False


def test_calculate_arpc_method1_deterministic_8_bytes():
    udk = cu.derive_udk(KEYS["imk_ac"], PAN, KEYS["pan_seq"])
    sk = cu.derive_session_key(udk, "0001")
    arqc_hex = "00" * 8
    arc_hex = "3030"  # ascii "00"

    arpc1 = cu.calculate_arpc_method1(arqc_hex, arc_hex, sk)
    arpc2 = cu.calculate_arpc_method1(arqc_hex, arc_hex, sk)
    assert arpc1 == arpc2
    assert len(arpc1) == 8


def test_pin_block_encrypt_and_verify_roundtrip():
    pin = "1234"
    plain = cu.encode_pin_block_format0(pin, PAN)
    assert len(plain) == 8

    encrypted = cu.encrypt_pin_block(plain, KEYS["pek"])
    f52_b64 = base64.b64encode(encrypted).decode()

    assert cu.verify_pin(PAN, f52_b64, KEYS["pek"], "1234") is True
    assert cu.verify_pin(PAN, f52_b64, KEYS["pek"], "9999") is False


def test_cvv2_roundtrip():
    expiry = "1227"  # MMYY
    cvv2 = cu.compute_cvv2(PAN, expiry, KEYS["cvk"])
    assert len(cvv2) == 3
    assert cvv2.isdigit()

    assert cu.verify_cvv2(PAN, expiry, cvv2, KEYS["cvk"]) is True
    assert cu.verify_cvv2(PAN, expiry, "000", KEYS["cvk"]) is False


def test_aav_roundtrip():
    f47_data = {"message_type": "0100", "f55": {"atc": "0001"}}
    aav = cu.compute_aav(f47_data, KEYS["aav_key"], PAN)
    f47_data["aav"] = aav

    assert cu.verify_aav(f47_data, KEYS["aav_key"], PAN) is True

    f47_data["aav"] = "tampered"
    assert cu.verify_aav(f47_data, KEYS["aav_key"], PAN) is False


@pytest.mark.parametrize("pan", list(PANS.keys()))
def test_all_pans_defined_keys_work(pan):
    keys = PANS[pan]
    udk = cu.derive_udk(keys["imk_ac"], pan, keys["pan_seq"])
    sk = cu.derive_session_key(udk, "0001")
    assert len(bytes.fromhex(sk)) == 16

    plain = cu.encode_pin_block_format0(keys["pin"], pan)
    encrypted = cu.encrypt_pin_block(plain, keys["pek"])
    f52_b64 = base64.b64encode(encrypted).decode()
    assert cu.verify_pin(pan, f52_b64, keys["pek"], keys["pin"]) is True

    cvv2 = cu.compute_cvv2(pan, "1227", keys["cvk"])
    assert cu.verify_cvv2(pan, "1227", cvv2, keys["cvk"]) is True

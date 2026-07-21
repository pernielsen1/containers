import base64
import json
import os

from shared import crypto_utils as cu

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(PROJECT_ROOT, "pans_defined.json")) as f:
    PANS = json.load(f)

PAN = "4111111111111111"
INFO = PANS[PAN]


def _f55():
    return {
        "amount_auth": "000000000100",
        "amount_other": "000000000000",
        "terminal_country": "0840",
        "terminal_verification_results": "0000000000",
        "currency_code": "0840",
        "transaction_date": "250101",
        "transaction_type": "00",
        "unpredictable_number": "12345678",
        "aip": "3800",
        "atc": "0001",
    }


def test_udk_and_session_key_are_deterministic():
    udk1 = cu.derive_udk(INFO["imk_ac"], PAN, INFO["pan_seq"])
    udk2 = cu.derive_udk(INFO["imk_ac"], PAN, INFO["pan_seq"])
    assert udk1 == udk2
    assert len(udk1) == 32

    sk = cu.derive_session_key(udk1, "0001")
    assert len(sk) == 32


def test_verify_arqc_accepts_valid_and_rejects_tampered():
    udk = cu.derive_udk(INFO["imk_ac"], PAN, INFO["pan_seq"])
    sk = cu.derive_session_key(udk, "0001")
    f55 = _f55()
    data = cu._pad_iso9797_2(cu._build_mac_input(f55))
    mac = cu._retail_mac(bytes.fromhex(sk), data)
    f55["cryptogram"] = mac.hex().upper()

    assert cu.verify_arqc(PAN, INFO["pan_seq"], INFO["imk_ac"], f55)

    tampered = dict(f55)
    tampered["cryptogram"] = "0" * 16
    assert not cu.verify_arqc(PAN, INFO["pan_seq"], INFO["imk_ac"], tampered)


def test_arpc_method1_produces_8_bytes():
    udk = cu.derive_udk(INFO["imk_ac"], PAN, INFO["pan_seq"])
    sk = cu.derive_session_key(udk, "0001")
    arpc = cu.calculate_arpc_method1("A" * 16, "3030", sk)
    assert len(arpc) == 8


def test_pin_block_roundtrip():
    block = cu.encode_pin_block_format0(INFO["pin"], PAN)
    encrypted = cu.encrypt_pin_block(block, INFO["pek"])
    b64 = base64.b64encode(encrypted).decode()

    assert cu.verify_pin(PAN, b64, INFO["pek"], INFO["pin"])
    assert not cu.verify_pin(PAN, b64, INFO["pek"], "0000")


def test_cvv2_roundtrip():
    cvv2 = cu.compute_cvv2(PAN, "1225", INFO["cvk"])
    assert len(cvv2) == 3
    assert cu.verify_cvv2(PAN, "1225", cvv2, INFO["cvk"])
    assert not cu.verify_cvv2(PAN, "1225", "000", INFO["cvk"])


def test_aav_roundtrip():
    f47_data = {"f14": "1225", "message_type": "0100"}
    aav = cu.compute_aav(f47_data, INFO["aav_key"], PAN)
    f47_data["aav"] = aav
    assert cu.verify_aav(f47_data, INFO["aav_key"], PAN)

    f47_data["aav"] = "wrong"
    assert not cu.verify_aav(f47_data, INFO["aav_key"], PAN)

"""Unit tests for shared/crypto_utils.py using known keys from pans_defined.json."""
import base64
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.crypto_utils import (
    derive_udk,
    derive_session_key,
    verify_arqc,
    calculate_arpc_method1,
    verify_pin,
    encode_pin_block_format0,
    encrypt_pin_block,
    verify_cvv2,
    compute_cvv2,
    verify_aav,
    compute_aav,
    _retail_mac,
    _build_arqc_input,
)

PANS_PATH = os.path.join(os.path.dirname(__file__), "..", "pans_defined.json")
with open(PANS_PATH) as _f:
    PANS = json.load(_f)

PAN  = "5111111111111111"
PDATA = PANS[PAN]

# Shared f55 test data (deterministic)
F55 = {
    "atc":                            "0001",
    "aip":                            "5800",
    "amount_auth":                    "000000001000",
    "amount_other":                   "000000000000",
    "terminal_country":               "0208",
    "terminal_verification_results":  "8480048000",
    "currency_code":                  "0978",
    "transaction_date":               "260530",
    "transaction_type":               "00",
    "unpredictable_number":           "A1B2C3D4",
}


class TestKeyDerivation(unittest.TestCase):

    def test_derive_udk_length(self):
        udk = derive_udk(PDATA["imk_ac"], PAN, PDATA["pan_seq"])
        self.assertEqual(len(udk), 32)  # 16 bytes

    def test_derive_udk_deterministic(self):
        udk1 = derive_udk(PDATA["imk_ac"], PAN, PDATA["pan_seq"])
        udk2 = derive_udk(PDATA["imk_ac"], PAN, PDATA["pan_seq"])
        self.assertEqual(udk1, udk2)

    def test_derive_session_key_length(self):
        udk = derive_udk(PDATA["imk_ac"], PAN, PDATA["pan_seq"])
        sk = derive_session_key(udk, "0001")
        self.assertEqual(len(sk), 32)

    def test_different_atc_gives_different_sk(self):
        udk = derive_udk(PDATA["imk_ac"], PAN, PDATA["pan_seq"])
        sk1 = derive_session_key(udk, "0001")
        sk2 = derive_session_key(udk, "0002")
        self.assertNotEqual(sk1, sk2)


def _make_valid_arqc(f55, pan, pan_data):
    """Compute a valid ARQC cryptogram for the given f55 input."""
    from shared.crypto_utils import _build_arqc_input
    udk = derive_udk(pan_data["imk_ac"], pan, pan_data["pan_seq"])
    sk  = derive_session_key(udk, f55["atc"])
    data_hex = _build_arqc_input(f55)
    arqc_bytes = _retail_mac(sk, data_hex)
    return arqc_bytes.hex().upper()


class TestARQC(unittest.TestCase):

    def setUp(self):
        self.f55 = dict(F55)
        self.f55["cryptogram"] = _make_valid_arqc(self.f55, PAN, PDATA)

    def test_verify_arqc_correct(self):
        self.assertTrue(verify_arqc(PAN, PDATA["pan_seq"], PDATA["imk_ac"], self.f55))

    def test_verify_arqc_wrong_cryptogram(self):
        bad = dict(self.f55)
        bad["cryptogram"] = "DEADBEEFCAFEBABE"
        self.assertFalse(verify_arqc(PAN, PDATA["pan_seq"], PDATA["imk_ac"], bad))

    def test_verify_arqc_wrong_atc(self):
        bad = dict(self.f55)
        bad["atc"] = "0099"
        # cryptogram was computed for atc=0001, so wrong atc → wrong session key → fail
        self.assertFalse(verify_arqc(PAN, PDATA["pan_seq"], PDATA["imk_ac"], bad))

    def test_verify_arqc_wrong_pan(self):
        self.assertFalse(
            verify_arqc("4111111111111111", PANS["4111111111111111"]["pan_seq"],
                        PANS["4111111111111111"]["imk_ac"], self.f55)
        )


class TestARPC(unittest.TestCase):

    def test_arpc_length(self):
        udk = derive_udk(PDATA["imk_ac"], PAN, PDATA["pan_seq"])
        sk  = derive_session_key(udk, "0001")
        arpc = calculate_arpc_method1("AABBCCDDEE112233", "3030", sk)
        self.assertEqual(len(arpc), 8)  # 8 bytes

    def test_arpc_different_arc(self):
        udk = derive_udk(PDATA["imk_ac"], PAN, PDATA["pan_seq"])
        sk  = derive_session_key(udk, "0001")
        arqc_hex = "AABBCCDDEE112233"
        arpc1 = calculate_arpc_method1(arqc_hex, "3030", sk)
        arpc2 = calculate_arpc_method1(arqc_hex, "3535", sk)
        self.assertNotEqual(arpc1, arpc2)


class TestPIN(unittest.TestCase):

    def _make_f52(self, pin, pan, pek_hex):
        plain = encode_pin_block_format0(pin, pan)
        encrypted = encrypt_pin_block(plain, pek_hex)
        return base64.b64encode(encrypted).decode()

    def test_correct_pin(self):
        f52 = self._make_f52("1234", PAN, PDATA["pek"])
        self.assertTrue(verify_pin(PAN, f52, PDATA["pek"], "1234"))

    def test_wrong_pin(self):
        f52 = self._make_f52("9999", PAN, PDATA["pek"])
        self.assertFalse(verify_pin(PAN, f52, PDATA["pek"], "1234"))

    def test_wrong_pek(self):
        f52 = self._make_f52("1234", PAN, PDATA["pek"])
        other_pek = PANS["4111111111111111"]["pek"]
        self.assertFalse(verify_pin(PAN, f52, other_pek, "1234"))

    def test_invalid_base64(self):
        self.assertFalse(verify_pin(PAN, "!!!notbase64!!!", PDATA["pek"], "1234"))


class TestCVV2(unittest.TestCase):

    def test_compute_and_verify(self):
        cvv2 = compute_cvv2(PAN, "1225", PDATA["cvk"])
        self.assertEqual(len(cvv2), 3)
        self.assertTrue(cvv2.isdigit())
        self.assertTrue(verify_cvv2(PAN, "1225", cvv2, PDATA["cvk"]))

    def test_wrong_cvv2(self):
        cvv2 = compute_cvv2(PAN, "1225", PDATA["cvk"])
        wrong = str((int(cvv2) + 1) % 1000).zfill(3)
        self.assertFalse(verify_cvv2(PAN, "1225", wrong, PDATA["cvk"]))

    def test_wrong_expiry(self):
        cvv2 = compute_cvv2(PAN, "1225", PDATA["cvk"])
        self.assertFalse(verify_cvv2(PAN, "0125", cvv2, PDATA["cvk"]))

    def test_different_pans_give_different_cvv2(self):
        cvv2_a = compute_cvv2("5111111111111111", "1225", PDATA["cvk"])
        cvv2_b = compute_cvv2("5222222222222222", "1225", PDATA["cvk"])
        self.assertNotEqual(cvv2_a, cvv2_b)


class TestAAV(unittest.TestCase):

    def _make_f47_data(self, msg_type="0100", f14="1225"):
        return {"message_type": msg_type, "f14": f14}

    def test_correct_aav(self):
        f47 = self._make_f47_data()
        aav = compute_aav(f47, PDATA["aav_key"], PAN)
        f47["aav"] = aav
        self.assertTrue(verify_aav(f47, PDATA["aav_key"], PAN))

    def test_wrong_aav(self):
        f47 = self._make_f47_data()
        f47["aav"] = base64.b64encode(b"\x00" * 20).decode()
        self.assertFalse(verify_aav(f47, PDATA["aav_key"], PAN))

    def test_tampered_f14(self):
        f47 = self._make_f47_data()
        aav = compute_aav(f47, PDATA["aav_key"], PAN)
        f47["aav"] = aav
        f47["f14"] = "9999"  # tamper expiry after AAV computed
        self.assertFalse(verify_aav(f47, PDATA["aav_key"], PAN))


if __name__ == "__main__":
    unittest.main()

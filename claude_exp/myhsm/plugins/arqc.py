"""ARQC (Application Request Cryptogram) calculation plugin.

Implements EMV ARQC using:
  1. ICC Master Key derivation from IMK via PAN/PSN (Option A, 2-key 3DES)
  2. Session key derivation from UDK via ATC — method selectable via sk_method
  3. ARQC = ISO 9797-1 Alg 3 MAC over CDOL1 transaction data

Session key derivation methods (sk_method):
  visa  (default) : Left  = 3DES_ECB(UDK, ATC || 00 00 00 00 00 00)
                    Right = 3DES_ECB(UDK, ATC || 00 00 00 00 00 FF)
  csk             : EMVCo Common Session Key (Book 2 Annex A1.3)
                    Left  = 3DES_ECB(UDK, ATC || 00 00 F0 00 00 00)
                    Right = 3DES_ECB(UDK, ATC || 00 00 0F 00 00 00)
  csd             : MC Card-Specific Derivation — UDK used directly (no ATC derivation)

Input dict keys:
  imk_token            : keystore token for the Issuer Master Key
  pan                  : Primary Account Number (string of digits)
  psn                  : PAN Sequence Number (default '01')
  sk_method            : session key derivation method: 'visa', 'csk', or 'csd' (default 'visa')
  amount               : amount in minor units, e.g. 1234 = 12.34 (default 0)
  amount_other         : secondary amount (default 0)
  currency             : ISO 4217 numeric currency code (default 0)
  terminal_country     : terminal country code as 4-hex-digit string (default '0000')
  tvr                  : Terminal Verification Results, 10 hex chars (default '0000000000')
  transaction_date     : YYMMDD as 6-char hex string (default today)
  transaction_type     : 2 hex chars (default '00' = purchase)
  unpredictable_number : 8 hex chars (default '00000000')
  aip                  : Application Interchange Profile, 4 hex chars (default '0000')
  atc                  : Application Transaction Counter, 4 hex chars (default '0001')

Returns:
  result_bool          : True on success
  arqc                 : 8-byte ARQC in uppercase hex
  sk_method            : session key method used
  udk                  : derived Unique Derivation Key (hex) — for debugging
  session_key          : derived session key (hex) — for debugging
  transaction_data     : raw CDOL1 data fed to MAC (hex) — for debugging
"""

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import keystore

from Crypto.Cipher import DES, DES3


def _tdes_ecb_block(key: bytes, block: bytes) -> bytes:
    """2-key 3DES ECB encrypt one 8-byte block: E(K1, D(K2, E(K1, x))).
    Works even when K1==K2 (single-DES equivalent), bypassing PyCryptodome's
    degenerate-key check."""
    k1, k2 = key[:8], key[8:16]
    step1 = DES.new(k1, DES.MODE_ECB).encrypt(block)
    step2 = DES.new(k2, DES.MODE_ECB).decrypt(step1)
    return DES.new(k1, DES.MODE_ECB).encrypt(step2)


def _tdes_ecb(key: bytes, data: bytes) -> bytes:
    """3DES ECB encrypt; key is 16 bytes (extended to 16 if 8-byte single-DES)."""
    if len(key) == 8:
        key = key + key
    return b"".join(_tdes_ecb_block(key, data[i:i+8]) for i in range(0, len(data), 8))


def _tdes_cbc(key: bytes, data: bytes, iv: bytes) -> bytes:
    """3DES CBC encrypt; returns ciphertext (same length as data)."""
    if len(key) == 8:
        key = key + key
    result, prev = b"", iv
    for i in range(0, len(data), 8):
        block = bytes(a ^ b for a, b in zip(data[i:i+8], prev))
        prev = _tdes_ecb_block(key, block)
        result += prev
    return result


def _ecb(key: bytes, data: bytes) -> bytes:
    return _tdes_ecb(key, data)


def _derive_udk(imk: bytes, pan: str, psn: str) -> bytes:
    """Derive ICC Master Key (UDK) from IMK using EMV Option A."""
    pan_right12 = pan[:-1][-12:]          # drop Luhn digit, take rightmost 12
    divers = bytes.fromhex(pan_right12 + psn.zfill(2) + "F0")  # 8 bytes BCD + pad
    complement = bytes(b ^ 0xFF for b in divers)
    return _ecb(imk, divers) + _ecb(imk, complement)


_SK_METHODS = ("visa", "csk", "csd")


def _derive_session_key(udk: bytes, atc_hex: str, method: str) -> bytes:
    """Derive AC session key from UDK and ATC.

    visa : Visa VIS — differentiator byte 0x00/0xFF at position 7
    csk  : EMVCo Common Session Key — differentiator F0/0F at position 4 (0-indexed)
    csd  : MC Card-Specific Derivation — UDK used directly, no ATC derivation
    """
    atc = bytes.fromhex(atc_hex.zfill(4))   # 2 bytes
    if method == "csd":
        return udk                           # MC: UDK is the session key
    if method == "csk":
        left  = _ecb(udk, atc + b'\x00\x00\xF0\x00\x00\x00')
        right = _ecb(udk, atc + b'\x00\x00\x0F\x00\x00\x00')
    else:                                    # visa (default)
        left  = _ecb(udk, atc + bytes(6))
        right = _ecb(udk, atc + bytes(5) + b'\xFF')
    return left + right


def _iso9797_m2(data: bytes, block: int = 8) -> bytes:
    """ISO 9797-1 padding method 2: append 0x80 then zeros to block boundary."""
    padded = data + b'\x80'
    rem = len(padded) % block
    return padded + bytes(block - rem if rem else 0)


def _mac_3des_cbc(key: bytes, data: bytes) -> bytes:
    """3DES CBC MAC, IV=0 — returns final 8-byte block."""
    return _tdes_cbc(key, data, bytes(8))[-8:]


def _bcd(value: int, digits: int) -> bytes:
    """Encode integer as BCD with the given number of decimal digits."""
    return bytes.fromhex(f"{value:0{digits}d}")


def run(input_data: dict) -> dict:
    imk_token = input_data.get("imk_token")
    pan = str(input_data.get("pan", ""))

    if not imk_token or not pan:
        return {"result_bool": False, "error": "imk_token and pan are required"}

    imk = keystore.get(imk_token)
    if imk is None:
        return {"result_bool": False, "error": f"key '{imk_token}' not found in keystore"}

    psn              = str(input_data.get("psn", "01")).zfill(2)
    sk_method        = str(input_data.get("sk_method", "visa")).lower()
    amount           = int(input_data.get("amount", 0))
    amount_other     = int(input_data.get("amount_other", 0))
    currency         = int(input_data.get("currency", 0))
    terminal_country = str(input_data.get("terminal_country", "0000")).zfill(4)
    tvr              = str(input_data.get("tvr", "0000000000")).zfill(10)
    atc              = str(input_data.get("atc", "0001")).zfill(4)
    aip              = str(input_data.get("aip", "0000")).zfill(4)
    trans_type       = str(input_data.get("transaction_type", "00")).zfill(2)
    un               = str(input_data.get("unpredictable_number", "00000000")).zfill(8)
    trans_date       = input_data.get("transaction_date",
                                      datetime.date.today().strftime("%y%m%d"))

    if sk_method not in _SK_METHODS:
        return {"result_bool": False,
                "error": f"sk_method must be one of {_SK_METHODS}"}

    try:
        udk = _derive_udk(imk, pan, psn)
        session_key = _derive_session_key(udk, atc, sk_method)

        # CDOL1 data: 6+6+2+5+2+3+1+4+2+2 = 33 bytes
        trans_data = (
            _bcd(amount, 12) +               # Amount Authorised (6 bytes)
            _bcd(amount_other, 12) +          # Amount Other      (6 bytes)
            bytes.fromhex(terminal_country) + # Terminal Country  (2 bytes)
            bytes.fromhex(tvr) +              # TVR               (5 bytes)
            _bcd(currency, 4) +               # Currency Code     (2 bytes)
            bytes.fromhex(trans_date) +       # Transaction Date  (3 bytes)
            bytes.fromhex(trans_type) +       # Transaction Type  (1 byte)
            bytes.fromhex(un) +               # Unpredictable Num (4 bytes)
            bytes.fromhex(aip) +              # AIP               (2 bytes)
            bytes.fromhex(atc)                # ATC               (2 bytes)
        )

        arqc = _mac_3des_cbc(session_key, _iso9797_m2(trans_data))

        return {
            "result_bool": True,
            "arqc": arqc.hex().upper(),
            "sk_method": sk_method,
            "udk": udk.hex().upper(),
            "session_key": session_key.hex().upper(),
            "transaction_data": trans_data.hex().upper(),
        }

    except Exception as exc:
        return {"result_bool": False, "error": str(exc)}

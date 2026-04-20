"""ARPC (Application Response Cryptogram) calculation plugin.

Proves to the card that the response came from the genuine issuer.
Uses the same session key as the ARQC (derive with identical IMK/PAN/PSN/ATC/sk_method).

Method 1 (EMVCo, default):
  arpc_input = ARQC XOR (ARC || 00 00 00 00 00 00)
  ARPC       = 3DES_ECB(session_key, arpc_input)          — 8 bytes

Method 2 (EMVCo):
  data = ARQC(8) || ARC(2) || CSU(4) [|| prop_auth_data]
  ARPC = first 4 bytes of 3DES_CBC_MAC(session_key, ISO9797-M2(data))

Input dict keys:
  imk_token      : keystore token for Issuer Master Key (same as used for ARQC)
  pan            : Primary Account Number
  psn            : PAN Sequence Number (default '01')
  sk_method      : 'visa' | 'csk' | 'csd' (default 'visa')
  atc            : Application Transaction Counter, 4 hex chars (default '0001')
  arqc           : ARQC value from the arqc plugin, 16 hex chars (8 bytes)
  arc            : Authorization Response Code, 4 hex chars (default '0000' = approved)
  arpc_method    : '1' or '2' (default '1')
  csu            : Card Status Update, 8 hex chars (method 2 only, default '00000000')
  prop_auth_data : Proprietary Authentication Data, hex string (method 2 only, optional)

Returns:
  result_bool    : True on success
  arpc           : ARPC in uppercase hex (8 bytes for method 1, 4 bytes for method 2)
  arpc_method    : method used
  session_key    : derived session key (hex) — for debugging
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import keystore

from plugins.arqc import (
    _derive_udk,
    _derive_session_key,
    _tdes_ecb,
    _iso9797_m2,
    _mac_3des_cbc,
    _SK_METHODS,
)

_ARPC_METHODS = ("1", "2")


def run(input_data: dict) -> dict:
    imk_token = input_data.get("imk_token")
    pan = str(input_data.get("pan", ""))
    arqc_hex = str(input_data.get("arqc", ""))

    if not imk_token or not pan or not arqc_hex:
        return {"result_bool": False, "error": "imk_token, pan, and arqc are required"}

    imk = keystore.get(imk_token)
    if imk is None:
        return {"result_bool": False, "error": f"key '{imk_token}' not found in keystore"}

    psn         = str(input_data.get("psn", "01")).zfill(2)
    sk_method   = str(input_data.get("sk_method", "visa")).lower()
    atc         = str(input_data.get("atc", "0001")).zfill(4)
    arc         = str(input_data.get("arc", "0000")).zfill(4)
    arpc_method = str(input_data.get("arpc_method", "1"))

    if sk_method not in _SK_METHODS:
        return {"result_bool": False, "error": f"sk_method must be one of {_SK_METHODS}"}
    if arpc_method not in _ARPC_METHODS:
        return {"result_bool": False, "error": f"arpc_method must be '1' or '2'"}

    try:
        arqc_bytes = bytes.fromhex(arqc_hex)
        arc_bytes  = bytes.fromhex(arc)
        if len(arqc_bytes) != 8:
            return {"result_bool": False, "error": "arqc must be 8 bytes (16 hex chars)"}
        if len(arc_bytes) != 2:
            return {"result_bool": False, "error": "arc must be 2 bytes (4 hex chars)"}

        udk = _derive_udk(imk, pan, psn)
        session_key = _derive_session_key(udk, atc, sk_method)

        if arpc_method == "1":
            # XOR ARQC with ARC padded to 8 bytes, then 3DES ECB
            arpc_input = bytes(a ^ b for a, b in zip(arqc_bytes, arc_bytes + bytes(6)))
            arpc_bytes = _tdes_ecb(session_key, arpc_input)
        else:
            # Method 2: MAC over ARQC || ARC || CSU [|| prop_auth_data]
            csu_hex       = str(input_data.get("csu", "00000000")).zfill(8)
            prop_hex      = str(input_data.get("prop_auth_data", ""))
            mac_data      = arqc_bytes + arc_bytes + bytes.fromhex(csu_hex)
            if prop_hex:
                mac_data += bytes.fromhex(prop_hex)
            arpc_bytes = _mac_3des_cbc(session_key, _iso9797_m2(mac_data))[:4]

        return {
            "result_bool": True,
            "arpc": arpc_bytes.hex().upper(),
            "arpc_method": arpc_method,
            "session_key": session_key.hex().upper(),
        }

    except Exception as exc:
        return {"result_bool": False, "error": str(exc)}

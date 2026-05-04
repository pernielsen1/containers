# crypto skill

HSM simulator and EMV/ISO 8583 crypto plugin knowledge.
Working directory: `/home/perni/containers/claude_exp/myhsm/`

Related project: ISO 8583 authorization test harness — see `/home/perni/.claude/commands/iso8583.md`

---

## What this project is

A Fortanix DSM-inspired HSM simulator built with Python/Flask. Plugins are Python scripts invoked via REST. The sim provides the crypto primitives needed to generate and verify ISO 8583 authorization message fields — PIN blocks (field 52), ICC data (field 55), ARQCs, etc.

---

## Project files

| File | Purpose |
|------|---------|
| `server.py` | Flask app — auth, key derivation endpoint, plugin dispatcher |
| `keystore.py` | In-memory keystore; loaded from `keystore.json` at startup |
| `keystore.json` | Key definitions: name → base64 value |
| `plugins/*.py` | One file per plugin; each exports `run(input_data: dict) -> dict` |
| `test_plugin.sh` | curl-based end-to-end test script |

---

## API

```
POST /sys/v1/session/auth          Basic auth → { access_token }
POST /crypto/v1/keys/derive        Derive key by XOR diversification
POST /crypto/v1/plugins/<name>     Invoke plugin by name (Bearer token required)
```

---

## Keystore (`keystore.json`)

Keys are identified by name or a derived token (`diversify + keyname`).

| Name | Value (hex) | Notes |
|------|-------------|-------|
| `des_key` | `0102030405060708` | 8-byte DES; used as IMK in ARQC tests |
| `des_key_out` | `C1C1C1C1C1C1C1C11C1C1C1C1C1C1C1C` | PIN translate outgoing key |
| `aes128_key` | 16 bytes | AES-128 |
| `aes256_key` | 32 bytes | AES-256 |

---

## Plugins

### `upper_case`
Input: `{ "input": "string" }` → `{ "result": "STRING" }`

### `lower_case`
Input: `{ "input": "string" }` → `{ "result_bool", "result_string" }` (fails if string starts with digit)

### `do_cipher`
DES/AES encrypt or decrypt using a keystore token.
Input: `key_token`, `algorithm` (`DES`/`AES`), `data` (base64), `iv` (hex, optional), `mode` (`encrypt`/`decrypt`)

### `pin_translate`
ISO 8583 field-52 PIN block re-encryption. Decrypts under `in_key_token`, re-encrypts under `out_key_token`.
Test case: PAN=`555551234567890`, PIN=`1234`, in=`des_key`, out=`des_key_out`
Input: `in_key_token`, `out_key_token`, `data` (base64), `iv` (hex, optional)

### `arqc`
Full EMV ARQC calculation: IMK → UDK → session key → 3DES CBC MAC.
Output includes `arqc` hex — pass it directly as input to the `arpc` plugin.

**Input parameters:**

| Parameter | Default | Notes |
|-----------|---------|-------|
| `imk_token` | — | required; keystore token for Issuer Master Key |
| `pan` | — | required; PAN string |
| `psn` | `01` | PAN Sequence Number |
| `sk_method` | `visa` | Session key derivation: `visa`, `csk`, `csd` |
| `amount` | `0` | Minor units (1234 = 12.34) |
| `amount_other` | `0` | |
| `currency` | `0` | ISO 4217 numeric |
| `terminal_country` | `0000` | 4 hex chars |
| `tvr` | `0000000000` | 10 hex chars |
| `transaction_date` | today | YYMMDD hex |
| `transaction_type` | `00` | 2 hex chars |
| `unpredictable_number` | `00000000` | 8 hex chars |
| `aip` | `0000` | 4 hex chars |
| `atc` | `0001` | 4 hex chars |

**Output:** `arqc`, `sk_method`, `udk`, `session_key`, `transaction_data` (all hex)

---

## ARQC algorithm detail

### 1. ICC Master Key derivation (EMV Option A, 2-key 3DES)
```
pan_right12 = PAN[:-1][-12:]          # drop Luhn check digit
divers      = BCD(pan_right12 + psn) + 0xF0   # 8 bytes
UDK = 3DES_ECB(IMK, divers) || 3DES_ECB(IMK, ~divers)
```
If IMK is 8-byte single DES → doubled to 16-byte (K||K) for 3DES. Implemented manually with single-DES primitives to bypass PyCryptodome's degenerate-key check.

### 2. Session key derivation

| `sk_method` | Left block (8 bytes) | Right block (8 bytes) |
|---|---|---|
| `visa` | ATC \|\| `000000000000` | ATC \|\| `00000000000FF` |
| `csk` | ATC \|\| `0000F0000000` | ATC \|\| `00000F000000` |
| `csd` | *(UDK used directly — no derivation)* | |

Session key = 3DES_ECB(UDK, left) \|\| 3DES_ECB(UDK, right)

### 3. ARQC (MAC)
CDOL1 transaction data (33 bytes):
```
amount(6) + amount_other(6) + terminal_country(2) + TVR(5) +
currency(2) + date(3) + trans_type(1) + UN(4) + AIP(2) + ATC(2)
```
Pad with ISO 9797-1 method 2 (0x80 + zero bytes to 8-byte boundary), then 3DES CBC MAC (IV=0).

### Test case
PAN=`555551234567890`, PSN=`01`, amount=`1234`, currency=`978`, IMK=`des_key`, ATC=`0001`, ARC=`0000`:

| sk_method | ARQC | ARPC/1 | ARPC/2 |
|-----------|------|--------|--------|
| visa | `5610B4DC43FA14AE` | `B679FC61CD4CD214` | `20822CD8` |
| csk | `05A3C1A505DA366E` | `29BAF5222073A020` | `8F7C8137` |
| csd | `9230EDAE84F1A93D` | `5C40C97598BB33BC` | `2E874D6F` |

---

## Running

```bash
cd /home/perni/containers/claude_exp/myhsm
python3 server.py          # starts on port 5000
bash test_plugin.sh        # runs curl tests
```

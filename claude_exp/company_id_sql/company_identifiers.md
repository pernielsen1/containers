# Company Identifiers — Skills & Knowledge Summary

## Overview

Company identifiers are official registration numbers used to uniquely identify legal entities in each country. This project validates them via:

- **Python class** `company_identifiers` in `snippets_copy/company_identifiers.py`
- **MySQL stored procedure** `validate_company_id` in `validate_company_id.sql`
- **Test harness** `test_company_id.py` — loads `company_ids.csv`, runs the procedure, and prints PASS/FAIL vs. expected

---

## Data Model

`company_ids` table (MySQL, database `db`):

| Column   | Type          | Description                         |
|----------|---------------|-------------------------------------|
| CNTRY    | CHAR(2)       | ISO country code                    |
| ID_TYPE  | CHAR(3)       | `CID` = company ID, `NAT` = natural |
| ID       | VARCHAR(100)  | Raw identifier string               |
| EXPECTED | TINYINT       | 1 = valid, 0 = invalid              |

---

## Core Parsing Pattern

All validators follow the same three-part split on the **cleaned** identifier string (dots, dashes, parentheses, spaces removed):

```
<before>  <number>  <after>
```

- **before** — leading non-digit characters (prefix/type indicator)
- **number** — contiguous digit block
- **after**  — trailing non-digit characters (suffix/court name)

SQL helpers: `fn_cid_clean`, `fn_cid_before`, `fn_cid_number`, `fn_cid_after`  
Python method: `get_before_number_after`

---

## Validation Algorithms

### Modulus 10 (Luhn-style)
Digits from right alternate: every other digit doubled, subtract 9 if > 9. Check digit = `10 - (sum % 10)` (0 if result is 10).

| Country | Name | Length | Weights / Notes |
|---------|------|--------|-----------------|
| SE | Organisationsnummer | 10 digits | Standard modulus 10, no prefix/suffix |
| FR | SIREN / SIRET | 9 or 14 digits | Modulus 10 on first 9 digits |
| ES | NIF | 7+letter or 8 digits | Prefix: A/B/C/F/G/N/W; modulus 10 on 8-digit form |

### Modulus 11 (weighted sum)
`sum = Σ(digit × weight)`. Check digit = `11 - (sum % 11)`. Special: remainder 0 → check digit 0; remainder 1 → check digit 0 (invalid in some countries).

| Country | Name | Length | Weights |
|---------|------|--------|---------|
| DK | CVR | 8 digits | 2,7,6,5,4,3,2,1 |
| NO | Organisationsnummer | 9 digits | 3,2,7,6,5,4,3,2,1 |
| FI | LY business ID | 8 digits (zero-padded) | 7,9,10,5,8,4,2,1 |
| PT | NIPC | 9 digits | 9,8,7,6,5,4,3,2 |
| CZ | IČO | 8 digits | 8,7,6,5,4,3,2 — remainder 0 → check digit **1** |
| CH | CHE (MWST) | 9 digits after CHE prefix | 5,4,3,2,7,6,5,4 |
| GR | AFM | 9 digits | 256,128,64,32,16,8,4,2 — `return_rest=True`, remainder 10 → 0 |

**Modulus 11 with round-2 fallback** (used when first pass gives remainder 10):

| Country | Name | Length | Round-1 weights | Round-2 weights |
|---------|------|--------|-----------------|-----------------|
| BG | UIC | 9 digits | 1,2,3,4,5,6,7,8 | 3,4,5,6,7,8,9,10 |
| EE | Registry code | 8 digits | 1,2,3,4,5,6,7 | 3,4,5,6,7,8,9 |
| LT | Legal identity code | 9 digits | 1,2,3,4,5,6,7,8 | 3,4,5,6,7,8,9,**1** |

### Modulus 97
`check = 97 - (first_N_digits % 97)` must equal the trailing 2-digit check pair.

| Country | Name | Length |
|---------|------|--------|
| BE | Ondernemingsnummer | 10 digits |

### ISO 7064 Mod-11/10
Iterative: `remainder = (remainder + digit) % 10`; if 0 set to 10; then `remainder = (remainder × 2) % 11`. Check digit = `11 - remainder` (10 → 0).

| Country | Name | Length |
|---------|------|--------|
| HR (OIB) | Personal/company ID | 11 digits |

---

## Country-Specific Rules

### Austria (AT)
- **FN / FB** prefix (or no prefix) + 1–6 digits + **lowercase letter** suffix
- **ZVR / FNZVR / FNZVRZAHL / ZVRZAHL** prefix + 9–10 digits
- SQL function: `fn_cid_before` must be in approved prefix list; suffix check digit must be `ASCII BETWEEN 97 AND 122`

### Germany (DE)
- Prefix: HRA, HRB, GnR, GsR, VR, PR
- 1–6 digit number + court name as suffix
- Full court name validation uses `XJustiz.json` (Python only; SQL validates prefix+length)

### Great Britain (GB)
- 8 digits (no prefix) → valid
- 2-letter prefix (SC, FC, BR, NI, OE, RC, OC, LP, SE, SO, SP, IP) + 6 digits → valid
- IP or SP + 5 digits + trailing `R` → valid
- Minimum prefix+digits: 5 total chars

### France (FR)
- SIREN: 9 digits (modulus 10 on first 8, check = digit 9)
- SIRET: 14 digits (same modulus 10 check on first 9)
- Suffix (e.g., "RCS Nantes") is allowed

### Italy (IT)
- Partita IVA: 11 digits, Luhn-variant with 1-based even positions doubled
- If first char is a letter (not `IT`): accepted as sole-trader code without digit check

### Croatia (HR)
- OIB: 11 digits — ISO 7064 check
- MBS: 9 digits — accepted as-is (no check digit)

### Switzerland (CH)
- `CHE-xxx.xxx.xxx` → modulus 11, weights [5,4,3,2,7,6,5,4], 9 digits
- `CH` + 11 digits → accepted as-is

### Mexico (MX)
- RFC: exactly 12 characters — 3 letters + 6-digit YYMMDD + 3 chars
- Date must be a valid calendar date in 2000–2099

### Romania (RO)
- J-number (Trade Register): `J<county>/<seq>/<YYYY>` — at least 3 slashes, leading `J`, year 1800–2099
- Compact format: `J` + 4-digit year + 9 remaining chars = 14 total chars
- Leading `/J/` also accepted

---

## Simple Numeric Validators
No check digit — only length and optional prefix matter.

| Country | Name | Format |
|---------|------|--------|
| CA | BN | 9 digits |
| HU | Adószám | 10 digits |
| IE | CRO | 3–6 digits |
| LI | Like CH | `FL` prefix + 11 digits |
| LU | RCS | B/F/G/J or no prefix + 1–6 digits; suffix allowed |
| LV | — | 11 digits |
| MT | ICO | `C` prefix + 3–5 digits |
| NL | KVK | 8 digits |
| PL | KRS | 10 digits |
| SI | — | 10 digits |
| SK | IČO | 8 digits |
| US | EIN | 9 digits |

---

## SQL Helper Functions

| Function | Purpose |
|----------|---------|
| `fn_cid_clean(s)` | Remove `.`, `-`, `(`, `)`, spaces |
| `fn_cid_before(s)` | Extract leading non-digit prefix |
| `fn_cid_number(s)` | Extract contiguous digit block |
| `fn_cid_after(s)` | Extract trailing non-digit suffix |
| `fn_modulus10_calc(s)` | Luhn-style check digit from n-1 digits |
| `fn_wsum(s, w1..w10)` | Weighted digit sum (up to 10 weights, cycling) |
| `fn_iso7064_calc(s)` | ISO 7064 Mod-11/10 for 10-digit input (HR OIB) |

---

## Files

| File | Role |
|------|------|
| `snippets_copy/company_identifiers.py` | Python class — master reference implementation |
| `snippets_copy/XJustiz.json` | German court name lookup |
| `validate_company_id.sql` | MySQL stored procedure + helper functions |
| `test_company_id.py` | Load CSV → run procedure → PASS/FAIL report |
| `company_ids.csv` | Test cases: CNTRY;ID_TYPE;ID;EXPECTED |

---

## Running the Tests

```bash
# Inside the container (PN_MYSQL_USER and PN_MYSQL_PASSWORD must be set)
python test_company_id.py
```

Output columns: `CNTRY  ID_TYPE  ID  EXP  GOT  PASS/FAIL`

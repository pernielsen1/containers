# AnaCredit — ECB Credit Register Reporting

You are working on a task related to the **AnaCredit** reporting framework (ECB Analytical Credit Datasets Regulation — ECB/2016/13). Use the knowledge below to assist accurately.

---

## What AnaCredit is

AnaCredit is the ECB's granular credit register. German banks report to the **Deutsche Bundesbank** monthly. It captures loan-level data on credit exposures ≥ €25,000 to legal entities.

- Legal basis: ECB Regulation ECB/2016/13 (as amended)
- Reporting agent: German credit institutions (Kreditinstitute)
- Threshold: credit exposures ≥ €25,000 per counterparty
- Frequency: monthly (reference date: last calendar day of month)
- Submission: XML to Deutsche Bundesbank

---

## Datasets (11 total)

| # | Dataset | Chapter |
|---|---------|---------|
| Ch.4 | Counterparty reference data | 29 attributes |
| 5.1 | Instrument dataset | 25 attributes |
| 5.2 | Financial dataset | 13 attributes |
| 5.3 | Counterparty-instrument dataset | 5 attributes |
| 5.4 | Joint liabilities dataset | 5 attributes |
| 5.5 | Accounting dataset | 18 attributes |
| 5.6 | Protection received dataset | 10 attributes |
| 5.7 | Instrument-protection received dataset | 5 attributes |
| 5.8 | Counterparty risk dataset | 3 attributes |
| 5.9 | Counterparty default dataset | 4 attributes |
| 5.10 | Protection provider dataset | 3 attributes |

**Total: 120 attributes** across 11 datasets (extracted to `anacredit_data_attributes.csv`).

---

## Project Files

All files are under `AnaCredit/` relative to the repo root (the directory containing the `AnaCredit/` folder — typically where you run Claude Code from):

| Path | Purpose |
|------|---------|
| `docs/anacredit-guidelines-data.pdf` | ECB AnaCredit reporting guidelines (English); chapters 4–5 cover all datasets and attributes |
| `docs/anacredit-codelist-version-2-8-data.xlsx` | **Authoritative** reference for all coded values (1,087 legal form codes, sector codes, etc.) — always prefer this over any URL in the PDF |
| `docs/anacredit-handbuch-validierungsregeln-version-22-data.pdf` | Deutsche Bundesbank validation rules handbook (German), v22 valid from 2026-08-01; section 4.1 = referential integrity (RI rules), section 4.2 = completeness rules (CY0010–CY0220), section 4.4 = consistency rules (CN_ prefix), section 4.5 = postal code format rules (130 countries) |
| `docs/List_of_national_identifiers.xlsx` | ECB list of national identifier types per country (v3.5); source for `national_id_types.json` |
| `src/extract_attributes.py` | Extracts all 120 data attributes from guidelines PDF → CSV; uses PyMuPDF (fitz), single-pass state machine over pages 57–145 |
| `src/validate_counterparty.py` | Field-level validator: completeness (CY0010–CY0220), consistency (CN_ prefix), national identifier type/format (CY0011_TYPE, CY0011_FMT), postal code formats (section 4.5); loads all codelists from JSON at startup |
| `src/validate_cp_xref.py` | Cross-reference validator: RI0140_DE, RI0150_DE, RI0160_DE — checks head office / immediate parent / ultimate parent exist as counterparties |
| `src/postal_code_validator.py` | Standalone `PostalCodeValidator` class; 130 country regex rules from `codelists/postal_code_formats.json` |
| `validate.sh` | Shell wrapper: runs both `validate_counterparty.py` and `validate_cp_xref.py`; exit code 1 if either finds errors |
| `anacredit_data_attributes.csv` | 120 attributes across 11 datasets; semicolon-delimited, utf-8-sig |
| `tests/sample_counterparty.csv` | 73-row test file: valid + format-error rows for all 28 EU countries plus US, CA, MX; also wrong-type, missing-type, and legacy error/warning rows |
| `tests/test_validate_counterparty.py` | 35 pytest unit tests: CY0011_TYPE, CY0011_FMT, CY0120 — run with `python3 -m pytest tests/` |

---

## Codelists Directory (`codelists/`)

All reference data is loaded from JSON — never hardcoded in Python source:

| File | Content |
|------|---------|
| `column_map.json` | 29 entries `{verbose, internal}` — single source of truth for column name mapping |
| `country_codes.json` | 238 ISO 3166-1 alpha-2 codes |
| `institutional_sectors.json` | ESA 2010 INSTTTNL_SCTR codes |
| `legal_forms.json` | 1,087 LGL_FRM codes extracted from codelist v2.8 Excel + `NOT_APPL`; loaded at startup, no Excel needed at runtime |
| `legal_proceeding_status.json` | `["1","2","3","4","NOT_APPL"]` |
| `enterprise_sizes.json` | `["1","2","3","4","NOT_APPL"]` |
| `cp_id_types.json` | `["1","2","3","4"]` |
| `accounting_standards.json` | `["1","2","3"]` |
| `reporting_member_states.json` | 27 EU reporting member states |
| `postal_code_formats.json` | 130 entries keyed by ISO: `{"DE": {"rule": "PSTL_CD_DS_D5", "pattern": "[0-9]{5}"}, ...}` |
| `national_id_types.json` | Three sections: `country_types` (allowed type codes per country), `formats` (regex per type code), `gen_codes` (generic codes valid for any country) — source: ECB v3.5 national identifiers list |

---

## National Identifier Validation

`validate_counterparty.py` implements two new rules for the `national_id` / `national_id_type` field pair:

**CY0011_TYPE** — fires when `national_id` is present (not NOT_APPL) and:
- `national_id_type` is missing (both must appear together), OR
- `national_id_type` is a country-specific code that does not belong to the counterparty's `country`

Generic codes (`GEN_TAX_CD`, `GEN_VAT_CD`, `GEN_OTHER_CD`, etc.) are accepted for any country. Countries not listed in `national_id_types.json` have no type restriction.

**CY0011_FMT** — fires when `national_id_type` has a regex entry in `national_id_types.json → formats` and `national_id` does not match `re.fullmatch(pattern, value)`. Types with no regex (e.g. `AT_NOTAP_CD`, `DE_NOTAP_CD`) skip format validation silently.

**Pattern notes:**
- All patterns use `re.fullmatch` — no anchors needed in the JSON
- Malformed patterns (compile error) are silently skipped
- `RO_TRN_CD` pattern uses `|` alternation (was incorrectly `" or "` in earlier versions — fixed in `national_id_types.json`)

---

## Validator CLI

```bash
cd AnaCredit  # from the repo root

# Run both validators (recommended)
./validate.sh tests/sample_counterparty.csv
./validate.sh data/counterparties.csv --summary
./validate.sh data/counterparties.csv --output report.csv --no-warnings

# Field-level validator only
python3 src/validate_counterparty.py tests/sample_counterparty.csv [--output results.csv] [--summary] [--no-warnings]

# Cross-reference validator only
python3 src/validate_cp_xref.py tests/sample_counterparty.csv [--output xref.csv] [--summary]

# Postal code spot-check
python3 src/postal_code_validator.py DE 12345

# Run unit tests
python3 -m pytest tests/
```

- Exit code `1` if any ERRORs found (pipeline-friendly); both validators run independently
- `validate_counterparty.py`: CY0010–CY0220 completeness + CY0011_TYPE/FMT national ID + CN_ consistency + postal code formats
- `validate_cp_xref.py`: RI0140_DE (head office), RI0150_DE (immediate parent), RI0160_DE (ultimate parent)
- Protected persons (`id_type = 'Protected'`) are exempt from RI checks
- Identifier existence always checked as `(id, id_type)` tuple pairs, not id alone
- No `--codelist` flag — legal form codes are always loaded from `codelists/legal_forms.json` at startup

---

## Sample Counterparty Records (`tests/sample_counterparty.csv` — 73 rows)

The file is organised in blocks by country. Key rows:

| CP ID | Country | Purpose |
|-------|---------|---------|
| 10070000 | DE | Deutsche Bank — valid large bank |
| CUST-001-VALID | DE | Valid GmbH; LEI missing → CY0010 WARNING |
| INTL0000000000001 | US | IMF — NOT_APPL on many fields |
| CUST-ERR-001 | XX | Deliberately invalid: bad LEI, invalid country/legal_form/sector → multiple ERRORs |
| CUST-WARN-001 | DE | Missing dates → CY0160 + CY0180 WARNINGs |
| CUST-WRONG-TYPE | DE | BE_OND_CD used for DE → CY0011_TYPE ERROR |
| CUST-MISSING-TYPE | DE | national_id present, type empty → CY0011_TYPE ERROR |
| CUST-AT-VALID / CUST-AT-FMT-ERR | AT | ATU12345678 valid; 12345678 → CY0011_FMT ERROR |
| CUST-BE-VALID / CUST-BE-FMT-ERR / CUST-BE-WRONG-TYPE | BE | Valid OND; format error; DE_VAT_CD type → type error |
| CUST-{CC}-VALID / CUST-{CC}-FMT-ERR | all others | One valid + one format-error row per country |
| CUST-US-GEN-OK | US | GEN_TAX_CD accepted for any country → no type error |

Countries with valid+format-error pairs: AT, BE, BG, CA, CY, CZ, DE, DK, EE, ES, FI, FR, GB, GR, HR, HU, IE, IT, LT, LU, LV, MT, MX, NL, PL, PT, RO, SE, SI, SK, US (30 countries).

---

## Counterparty Reference Data — 29 Attributes

The 29 attributes for chapter 4 (counterparty reference data) include:
- Identifiers: `CNTRPRTY_ID`, `TYP_CP_ID`, `NM_CP` (name), `LEI` (Legal Entity Identifier)
- Address: `ADDRS_STRТ`, `CITY`, `PSTL_CD`, `CNTRY` (ISO 3166-1 alpha-2)
- Classification: `INSTTTNL_SCTR` (ESA 2010 sector), `LGL_FRM` (legal form from codelist), `SZ` (enterprise size), `ACCNTNG_FRMWRK` (accounting standard)
- Status: `LGL_PRCDNG_STTS` (legal proceeding status), `DT_INCPRTN` (date of incorporation)
- Economics: `NTNL_IDNTFR`, `CNTRY_INCPRTN`, `HD_OFFC` (head office counterparty ID)

**Key coded values:**
- `INSTTTNL_SCTR`: ESA 2010 codes (S11, S121, S122, S123, S124, S125, S126, S127, S128, S129, S1311–S1314, S14, S15, or `-4` for non-applicable)
- `LGL_FRM`: 1,087 codes from `codelists/legal_forms.json` (extracted from codelist v2.8 Excel) — never hardcode
- `SZ`: `1` (micro), `2` (small), `3` (medium), `4` (large), `NOT_APPL`
- `LGL_PRCDNG_STTS`: `1`–`4` or `NOT_APPL`
- `ACCNTNG_FRMWRK`: `1` (IFRS), `2` (national GAAP), `3` (other)

---

## CSV Conventions (confirmed)

- Separator: **semicolon** (`;`)
- Encoding: **`utf-8-sig`** (UTF-8 with BOM) — preserves ü, ä, ö and other international characters
- No Excel output — CSV only
- Non-applicable values: use the string `NOT_APPL`

---

## Extending to Other Datasets

When building validators for instrument, financial, or other datasets:
1. Reference the relevant section of the validation rules handbook (German) for CN_ consistency rules
2. Always load coded values from the codelist Excel or JSON files — never hardcode
3. Follow the same CSV convention (semicolon, utf-8-sig)
4. Use exit code 1 on any ERROR for pipeline compatibility
5. The codelist Excel is always the authoritative source for allowed coded values
6. Cross-reference checks always use `(identifier, identifier_type)` tuple pairs, not identifier alone

---

## Banking Environment Notes

- Zero runtime internet dependencies (all reference data loaded from local files)
- PyMuPDF (`fitz`), `openpyxl`, and `pandas` are the only non-stdlib dependencies
- Self-contained — suitable for air-gapped banking environments

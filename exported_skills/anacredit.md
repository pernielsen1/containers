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
| `src/extract_attributes.py` | Extracts all 120 data attributes from guidelines PDF → CSV; uses PyMuPDF (fitz), single-pass state machine over pages 57–145 |
| `src/validate_counterparty.py` | Field-level validator: completeness (CY0010–CY0220), consistency (CN_ prefix), postal code formats (section 4.5); loads codelists from JSON at startup |
| `src/validate_cp_xref.py` | Cross-reference validator: RI0140_DE, RI0150_DE, RI0160_DE — checks head office / immediate parent / ultimate parent exist as counterparties |
| `src/postal_code_validator.py` | Standalone `PostalCodeValidator` class; 130 country regex rules from `codelists/postal_code_formats.json` |
| `validate.sh` | Shell wrapper: runs both `validate_counterparty.py` and `validate_cp_xref.py`; exit code 1 if either finds errors |
| `anacredit_data_attributes.csv` | 120 attributes across 11 datasets; semicolon-delimited, utf-8-sig |
| `sample_counterparty.csv` | 7 sample counterparty records covering all test cases (see below) |

---

## Codelists Directory (`codelists/`)

All reference data is loaded from JSON — never hardcoded in Python source:

| File | Content |
|------|---------|
| `column_map.json` | 29 entries `{verbose, internal}` — single source of truth for column name mapping |
| `country_codes.json` | 238 ISO 3166-1 alpha-2 codes |
| `institutional_sectors.json` | ESA 2010 INSTTTNL_SCTR codes |
| `legal_proceeding_status.json` | `["1","2","3","4","NOT_APPL"]` |
| `enterprise_sizes.json` | `["1","2","3","4","NOT_APPL"]` |
| `cp_id_types.json` | `["1","2","3","4"]` |
| `accounting_standards.json` | `["1","2","3"]` |
| `reporting_member_states.json` | 27 EU reporting member states |
| `postal_code_formats.json` | 130 entries keyed by ISO: `{"DE": {"rule": "PSTL_CD_DS_D5", "pattern": "[0-9]{5}"}, ...}` |

---

## Validator CLI

```bash
cd AnaCredit  # from the repo root

# Run both validators (recommended)
./validate.sh sample_counterparty.csv
./validate.sh data/counterparties.csv --summary
./validate.sh data/counterparties.csv --output report.csv --no-warnings

# Field-level validator only
python3 src/validate_counterparty.py sample_counterparty.csv [--output results.csv] [--summary] [--no-warnings]

# Cross-reference validator only
python3 src/validate_cp_xref.py sample_counterparty.csv [--output xref.csv] [--summary]

# Postal code spot-check
python3 src/postal_code_validator.py DE 12345
```

- Exit code `1` if any ERRORs found (pipeline-friendly); both validators run independently
- `validate_counterparty.py`: CY0010–CY0220 completeness + CN_ consistency + postal code formats
- `validate_cp_xref.py`: RI0140_DE (head office), RI0150_DE (immediate parent), RI0160_DE (ultimate parent)
- Protected persons (`id_type = 'Protected'`) are exempt from RI checks
- Identifier existence always checked as `(id, id_type)` tuple pairs, not id alone

---

## Sample Counterparty Records (`sample_counterparty.csv` — 7 rows)

| Row | CP ID | Purpose |
|-----|-------|---------|
| 2 | 10070000 | Deutsche Bank — valid large bank; head_office_id=self → RI0140_DE OK |
| 3 | CUST-001-VALID | Valid domestic GmbH; no cross-refs; LEI missing → CY0010 WARNING |
| 4 | INTL0000000000001 | IMF — valid international org, NOT_APPL on many fields |
| 5 | CUST-ERR-001 | Deliberately invalid: bad LEI, invalid country/legal_form/sector/size/accounting → multiple ERRORs |
| 6 | CUST-WARN-001 | head_office_id=10020000 (type=3) → references row 7 → RI0140_DE OK; missing dates → WARNINGs |
| 7 | 10020000 | Konzern Holding GmbH — exists to satisfy CUST-WARN-001's head office reference |
| 8 | CUST-XREF-BAD | ultimate_parent_id=GHOST-PARENT-999 → does not exist → RI0160_DE ERROR |

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
- `LGL_FRM`: 1,087 codes from codelist v2.8 Excel — never hardcode, always load from file
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

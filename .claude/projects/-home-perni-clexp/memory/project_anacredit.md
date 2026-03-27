---
name: AnaCredit skill
description: Context, files, and approach for AnaCredit data extraction and validation (ECB credit register)
type: project
---

AnaCredit is a European Central Bank (ECB) credit register reporting framework. The user works with AnaCredit guidelines in a banking context (Deutsche Bundesbank).

## Source documents
- `/home/perni/clexp/AnaCredit/docs/anacredit-guidelines-data.pdf` — ECB AnaCredit reporting guidelines (English), chapters 4-5 cover datasets and data attributes
- `/home/perni/clexp/AnaCredit/docs/anacredit-codelist-version-2-8-data.xlsx` — authoritative reference for coded values; use this instead of any URLs in the PDF
- `/home/perni/clexp/AnaCredit/docs/anacredit-handbuch-validierungsregeln-version-22-data.pdf` — Deutsche Bundesbank validation rules handbook (German), v22 valid from 01.08.2026; Section 4.2 covers counterparty completeness rules (CY0010–CY0220), Section 4.4 covers consistency rules (CN_ prefix)

## Scripts
- `/home/perni/clexp/AnaCredit/src/extract_attributes.py` — extracts all data attributes from guidelines PDF to CSV; uses PyMuPDF (fitz), single-pass state machine, pages 57-145
- `/home/perni/clexp/AnaCredit/src/validate_counterparty.py` — validates counterparty CSV data against validation rules; loads legal form codes from codelist Excel at startup

## Output files
- `/home/perni/clexp/AnaCredit/anacredit_data_attributes.csv` — 120 attributes across 11 datasets; semicolon-delimited, utf-8-sig encoding
- `/home/perni/clexp/AnaCredit/sample_counterparty.csv` — 5 sample counterparty records for testing the validator

## CSV conventions (confirmed preferences)
- Separator: semicolon (`;`)
- Encoding: `utf-8-sig` (UTF-8 with BOM) — preserves ü, ä, ö and other international characters
- No Excel output — CSV only

## Extracted datasets (120 attributes total)
- Chapter 4: Counterparty reference data (29)
- Chapter 5: Instrument dataset (25), Financial dataset (13), Counterparty-instrument dataset (5), Joint liabilities dataset (5), Accounting dataset (18), Protection received dataset (10), Instrument-protection received dataset (5), Counterparty risk dataset (3), Counterparty default dataset (4), Protection provider dataset (3)

## Validator details
- Implements completeness rules CY0010–CY0220 and consistency rules (CN_ prefix) for counterparty reference data
- Loads 1,087 legal form codes from codelist Excel; zero runtime internet dependencies
- CLI: `python3 validate_counterparty.py <input.csv> [--output results.csv] [--no-warnings] [--summary]`
- Exit code 1 if any ERRORs found (pipeline-friendly)

## How to apply
- When extending validation to other datasets (instrument, financial, etc.) — follow the same pattern as validate_counterparty.py, referencing the relevant section of the validation rules handbook
- The codelist Excel is always the authoritative source for allowed coded values
- All new CSVs: semicolon separator, utf-8-sig encoding

---
name: CSV encoding preference
description: User prefers semicolon-delimited UTF-8 CSVs over Excel files
type: feedback
---

Always use semicolon (`;`) as CSV separator and `utf-8-sig` encoding for all CSV output files.

**Why:** Semicolons avoid conflicts with decimal commas — this user's CSVs use `,` as the decimal separator (European convention). utf-8-sig (UTF-8 with BOM) preserves international characters (ü, ä, ö etc.) when opened in Excel. An attempt to generate Excel (.xlsx) output was made but deemed not successful — user explicitly chose CSV-only.

**How to apply:** Any time a script writes CSV output, use `delimiter=";"` and `encoding="utf-8-sig"`. When parsing numeric values from CSVs, treat `,` as the decimal separator (e.g. `1.234,56` = 1234.56). Do not offer Excel as an alternative output format unless explicitly asked.

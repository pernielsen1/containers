# ACPT/PROD compare pipeline (pandas_play)

Converts multi-sheet xlsb extracts into per-key CSVs, then compares an ACPT
extract against a PROD extract and reports what's missing, extra, or changed.

Project: `~/containers/claude_exp/pandas_play/`

## What this skill does

Two-stage pipeline:
1. `0_xlsb_to_csv.py` — splits a large xlsb (up to ~30M rows, 1M-row sheet cap)
   into one CSV per distinct value of an "area" field, one such split per
   source file (ACPT and PROD), landing in `output/compare/ACPT/` and
   `output/compare/PROD/`.
2. `1_compare.py` — for each filename present in either folder, diffs the
   ACPT and PROD versions using per-file key/ignore rules from `schema.json`.

## Step 1 — xlsb → CSV (`0_xlsb_to_csv.py`)

- `find_source_files(input_dir)` expects exactly one filename containing
  `"acpt"` and one containing `"prod"` (case-insensitive) in
  `/mnt/c/users/perni/OneDrive/Documents/wsl_input/test_xlsb`.
- `config.json` maps filename patterns (via `fnmatch`) to an
  `area_field_name` (the column used to split rows into separate CSVs, e.g.
  `"area"`).
- `XlsbToCSV` streams each sheet in `chunk_size` row batches (default 50k),
  groups each chunk by `area_field_name`, and appends to
  `output/compare/<ACPT|PROD>/<area_value>.csv` (semicolon-separated,
  utf-8-sig — see [[feedback_csv_encoding]]).
- `_check_no_upcast` guards against pandas silently upcasting an
  all-integer-but-missing column to float (`.0` suffix bug) — raises instead
  of writing corrupted data.
- Output files are named purely by area value (no ACPT/PROD in the
  filename) — the ACPT/PROD distinction is the containing folder, so the
  same filename in both folders is the compare pair.

Run:
```bash
python3 0_xlsb_to_csv.py
```

## Step 2 — compare (`1_compare.py`)

Schema file `schema.json` (project root) defines, per output filename:
```json
{
  "1234.csv": {
    "keys": ["area", "attrib", "rel"],
    "ignore": ["ign_01"]
  }
}
```
- `keys` — columns identifying "the same record" across ACPT/PROD.
- `ignore` — columns dropped before any comparison (noise fields).
- Everything else is an **attribute** — compared for equality when keys match.

Outputs (all under `output/`):
| Folder | Contents |
|---|---|
| `BOTH/` | Rows whose key exists in both ACPT and PROD (ACPT-side values), regardless of whether attributes differ |
| `BOTH_CHANGED/` | Subset of the above where at least one attribute differs; columns are `keys..., <attr>_ACPT, <attr>_PROD, ...` paired per attribute |
| `ONLY_ACPT/` | Rows whose key exists only in ACPT (or file exists only in ACPT dir) |
| `ONLY_PROD/` | Rows whose key exists only in PROD (or file exists only in PROD dir) |

Note: BOTH and BOTH_CHANGED are **not** mutually exclusive — a changed key
appears in both (unchanged rows appear only in BOTH). This was a deliberate
choice, not a default to assume elsewhere.

Run:
```bash
python3 1_compare.py
```

## Known real bugs hit while building this (feed forward)

- Schema file must be `schema.json` (dot), not `schema,json` (comma) —
  a typo that silently produced "file not found" rather than a clear error.
- `ignore` column names must match the CSV header **exactly** — a
  `ign_01` vs `igg_01` mismatch meant the ignore column silently stayed in
  the comparison instead of being dropped. No validation currently catches
  this; if schema.json changes, sanity-check ignored/key names against
  actual CSV headers.

## Related

[[feedback_csv_encoding]] — semicolon separator, utf-8-sig, no Excel output
[[feedback_spec_driven_builds]] — real bugs found here should be reflected
back into `input.md`/spec discussions, not just silently fixed in code

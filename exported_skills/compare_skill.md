# ACPT/PROD compare pipeline (pandas_play)

Converts xlsb extracts (single-sheet-with-area-column, or one-sheet-per-area)
into per-key CSVs, then compares an ACPT extract against a PROD extract and
reports what's missing, extra, or changed.

Project: `~/containers/claude_exp/pandas_play/`

## What this skill does

Three scripts, one shared helper module:
1. `0_xlsb_to_csv.py` — splits a large xlsb (up to ~30M rows, 1M-row sheet cap)
   where one sheet holds many areas distinguished by an "area" column, into
   one CSV per distinct area value.
2. `0_xlsb_multi_sto_csv.py` — variant for xlsb files structured as one sheet
   *per* area (area identity comes from the sheet name, not a column); skips
   sheets not listed in `multi_sheets.json`.
3. `1_compare.py` — for each filename present in either ACPT or PROD output,
   diffs the two versions using per-file key/ignore rules from `schema.json`.

Both converters write to the same `output/compare/ACPT/` and
`output/compare/PROD/` folders, so their outputs merge into one input set for
step 3 — same filename in both folders is a compare pair, regardless of which
converter produced it.

`xlsb_common.py` holds logic shared by all three scripts (CSV read/write,
value cleaning, filename safety, upcast guard, ACPT/PROD file discovery) —
see "Shared helpers" below. **This is the one file to carry over if porting
just the CSV-encoding convention to a different environment/repo** — it has
no project-specific dependencies (only `os`/`pandas`).

## config.json

Central config for both converters (not used by `1_compare.py`):
```json
{
  "one_drive": "/mnt/c/users/perni/OneDrive/Documents/",
  "input_paths": {
    "xlsb_to_csv": "wsl_input/test_xlsb",
    "xlsb_multi_sto_csv": "wsl_input/test_multi_sheet"
  },
  "file_patterns": [
    {"pattern": "*test_xlsb_file.xlsb", "area_field_name": "area", ...}
  ]
}
```
`config_utils.get_input_dir(config, input_key)` joins `one_drive` +
`input_paths[input_key]`. `file_patterns` (matched via `fnmatch`, used only by
`0_xlsb_to_csv.py`) maps an input filename pattern to its `area_field_name`.

## Step 1 — xlsb → CSV, single-sheet variant (`0_xlsb_to_csv.py`)

- `find_source_files(input_dir)` (from `xlsb_common`) expects exactly one
  filename containing `"acpt"` and one containing `"prod"` (case-insensitive).
- `XlsbToCSV` streams each sheet in `chunk_size` row batches (default 50k),
  groups each chunk by `area_field_name`, and appends to
  `output/compare/<ACPT|PROD>/<area_value>.csv`.
- Output files are named purely by area value (no ACPT/PROD in the
  filename) — the ACPT/PROD distinction is the containing folder.

Run: `python3 0_xlsb_to_csv.py`

## Step 1b — xlsb → CSV, one-sheet-per-area variant (`0_xlsb_multi_sto_csv.py`)

- `multi_sheets.json` (project root) maps sheet name → area name, e.g.
  `{"xyz": "XYZ_", "abc": "ABC"}`. Sheets not present as a key are skipped
  entirely (e.g. an "ign" sheet meant to be excluded).
- No `area` column exists in these sheets at all — area identity is purely
  positional (which sheet it came from), so there's no groupby: the whole
  sheet's rows go to `output/compare/<ACPT|PROD>/<mapped_area_name>.csv`.
- Different sheets can have entirely different column layouts (this is
  expected — each area is its own little schema).

Run: `python3 0_xlsb_multi_sto_csv.py`

## Step 2 — compare (`1_compare.py`)

Schema file `schema.json` (project root) defines, per output filename:
```json
{
  "1234.csv": { "keys": ["area", "attrib", "rel"], "ignore": ["ign_01"] },
  "XYZ_.csv": { "keys": ["account", "rel"] }
}
```
- `keys` — columns identifying "the same record" across ACPT/PROD.
- `ignore` — columns dropped before any comparison (noise fields).
- Everything else is an **attribute** — compared for equality when keys match.
- The schema key is the **generated filename** (area value from
  `area_field_name` or `multi_sheets.json`, not the sheet name or source
  filename) — e.g. sheet `"xyz"` mapped to area `"XYZ_"` needs a
  `"XYZ_.csv"` entry, not `"xyz.csv"`.

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

Run: `python3 1_compare.py`

## Shared helpers (`xlsb_common.py`)

- `write_csv(df, filepath, mode="w", header=True)` / `read_csv(filepath, dtype=str)`
  — the single choke point for CSV I/O in this project. Always semicolon
  separator + `utf-8-sig` encoding (BOM required for Excel to render ä, ö, ü,
  ß, å correctly instead of mojibake; semicolon avoids clashing with the
  comma decimal separator in European locales) — see [[feedback_csv_encoding]].
  All three scripts route every CSV read/write through these two functions
  rather than calling `pd.read_csv`/`to_csv` directly, specifically so the
  encoding convention can't silently drift in one call site.
- `clean_value`/`to_str` — collapses whole-number floats (`1234.0`) to int
  before stringifying, so ids don't grow a spurious `.0`.
- `safe_filename` — sanitizes an area value into a safe CSV filename.
- `check_no_upcast` — guards against pandas silently upcasting an
  all-integer-but-missing column to float (`.0` suffix bug) — raises instead
  of writing corrupted data.
- `find_source_files` — locates the one ACPT/one PROD file in a directory.

## Known real bugs hit while building this (feed forward)

- Schema file must be `schema.json` (dot), not `schema,json` (comma) —
  a typo that silently produced "file not found" rather than a clear error.
- `ignore` column names must match the CSV header **exactly** — a
  `ign_01` vs `igg_01` mismatch meant the ignore column silently stayed in
  the comparison instead of being dropped. No validation currently catches
  this; if schema.json changes, sanity-check ignored/key names against
  actual CSV headers.
- schema.json keys must match the *generated* filename (area value), not the
  source sheet name — `xyz.csv`/`abc.csv` entries silently wouldn't match the
  actual `XYZ_.csv`/`ABC.csv` files produced by the multi-sheet map.

## Related

[[feedback_csv_encoding]] — semicolon separator, utf-8-sig, no Excel output
[[feedback_spec_driven_builds]] — real bugs found here should be reflected
back into `input.md`/spec discussions, not just silently fixed in code

# Archive — JSON File Archiver

You are working on the **data_archive** project. Use the context below to assist accurately.

---

## What it does

A two-pass pipeline for archiving and extracting fields from JSON files.

- **Pass 1** — reads `input/`, validates, compresses (gzip+base64), appends to `output/pass1/archive.csv`
- **Pass 2** — reads `archive.csv` and `to_be_extracted.csv`, traverses JSON paths, writes flat rows to `output/pass2/extracted.csv`

---

## Directory structure

```
data_archive/
├── input/                    Drop key_type_<suffix>.json files here
├── committed/                Files successfully archived (pass 1)
├── error/                    Files that failed validation (pass 1)
├── output/
│   ├── pass1/archive.csv     Compressed archive (pass 1 output)
│   └── pass2/extracted.csv   Flat field extraction (pass 2 output)
├── backups/                  Timestamped copies of archive.csv
├── extract/                  Output of extract.py single-record tool
├── src/
│   ├── parser.py             Filename → (key, type, suffix)
│   ├── validator.py          JSON validity check
│   ├── archiver.py           gzip+base64, CSV append, crash recovery
│   ├── processor.py          Pass 1 orchestration + filelock
│   ├── extractor.py          Extractor class (latest / all versions)
│   └── field_extractor.py    Pass 2 field extraction engine
├── tests/                    pytest suite (51 tests)
├── run.py                    Pass 1 entry point
├── fields.py                 Pass 2 entry point
├── extract.py                Single-record extraction tool
├── backup.py                 Backup archive.csv with timestamp
├── pass1.sh                  Shell wrapper for pass 1
├── pass2.sh                  Shell wrapper for pass 2
├── reg_test.sh               End-to-end regression test
├── to_be_extracted.csv       Field extraction rules for pass 2
└── howto.txt                 Usage reference
```

---

## archive.csv format (pass 1 output)

| Column | Description |
|--------|-------------|
| `key` | First `_`-delimited segment of the filename |
| `type` | Second `_`-delimited segment of the filename |
| `suffix` | Remainder of the stem (dunsNumber, timestamp, version, etc.) |
| `base64_json` | gzip-compressed JSON, base64-encoded |

Separator: `;` — Encoding: utf-8-sig

---

## to_be_extracted.csv format (pass 2 config)

| Column | Description |
|--------|-------------|
| `key` | Exact match on archive key |
| `type` | Exact match on archive type |
| `path` | Dot-notation JSON path, supports array indexing (`companies[0].address.town`) |
| `output_col` | Column name in extracted.csv |

No wildcards. Missing paths produce an empty string.

---

## Input file naming

Pattern: `key_type_<suffix>.json`
- `key` and `type` must not contain underscores
- `suffix` is free-form: dunsNumber, timestamp, version (e.g. `350575093._v1`)
- Files not matching this pattern go to `error/`

---

## Versioning

`archive.csv` is **append-only**. Multiple versions of the same entity are stored as separate rows distinguished by suffix. Pass 2 outputs all versions. `extract.py` supports `--version latest` (highest suffix lexicographically) and `--version all`.

---

## Key commands

```bash
# Pass 1 — compress and archive
./pass1.sh
python3 run.py [base_dir]

# Pass 2 — extract fields
./pass2.sh
python3 fields.py [base_dir]

# Extract a single record
python3 extract.py <key> <type>                          # latest version (default)
python3 extract.py <key> <type> --version all            # all versions
python3 extract.py <key> <type> --csv path/to/archive.csv

# Backup archive.csv
python3 backup.py

# Full regression test
./reg_test.sh

# Unit tests
python3 -m pytest tests/ -v
```

---

## Resilience design

- **Append-only**: each CSV line is flushed individually — a crash corrupts at most the in-progress line
- **Crash recovery**: on startup `ensure_csv_intact()` truncates any partial last line
- **Concurrency**: `filelock` holds an exclusive lock on `archive.csv.lock` for the full batch

---

## Source module responsibilities

| Module | Responsibility |
|--------|---------------|
| `parser.py` | `parse_filename(name) -> (key, type, suffix)` |
| `validator.py` | `validate_json(content) -> bool` |
| `archiver.py` | `compress_to_base64`, `decompress_from_base64`, `ensure_csv_intact`, `write_header_if_needed`, `append_to_csv` |
| `processor.py` | `process_input(base_dir) -> stats dict` |
| `extractor.py` | `Extractor(csv).extract_latest(k,t)`, `extract_all(k,t)`, `extract(k,t)` |
| `field_extractor.py` | `extract_fields(archive_csv, rules_csv, output_csv) -> int` |

---

## Dependencies

- stdlib: `gzip`, `base64`, `csv`, `json`, `pathlib`, `uuid`, `shutil`, `argparse`
- external: `filelock` (`pip install filelock`)

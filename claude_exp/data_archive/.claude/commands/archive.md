# Archive — JSON File Archiver

You are working on the **data_archive** project. Use the context below to assist accurately.

---

## What it does

Processes JSON files from `input/`, validates them, compresses (gzip) and base64-encodes the content,
and appends each entry as a row in `output/archive.csv`. Processed files move to `committed/`;
invalid files move to `error/`.

---

## Directory structure

```
data_archive/
├── input/        Drop key_type_<suffix>.json files here
├── committed/    Files successfully archived
├── error/        Files that failed (bad name or invalid JSON)
├── output/       archive.csv  (semicolon-separated, utf-8-sig)
├── src/
│   ├── parser.py     Filename → (key, type)
│   ├── validator.py  JSON validity check
│   ├── archiver.py   gzip+base64, CSV append, crash recovery
│   ├── processor.py  Orchestration + filelock
│   └── extractor.py  Extractor class + CLI
├── tests/        pytest suite (46 tests)
├── run.py        Entry point
└── howto.txt     Usage reference
```

---

## CSV format

| Column | Description |
|--------|-------------|
| `key` | First segment of the filename |
| `type` | Second segment of the filename |
| `base64_json` | gzip-compressed JSON, base64-encoded |

Separator: `;` — Encoding: utf-8-sig (BOM for Excel compatibility)

---

## Input file naming

Pattern: `key_type_<anything>.json`
- `key` and `type` must not contain underscores
- The suffix (`<anything>`) can be a timestamp or any string
- Files not matching this pattern go to `error/`

---

## Key commands

```bash
# Process all files in input/
python3 run.py

# Process from a different base directory
python3 run.py /path/to/base

# Extract a record by key and type
python3 -m src.extractor <key> <type>
python3 -m src.extractor <key> <type> /path/to/archive.csv

# Run tests
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
| `parser.py` | `parse_filename(name) -> (key, type)` |
| `validator.py` | `validate_json(content) -> bool` |
| `archiver.py` | `compress_to_base64`, `decompress_from_base64`, `ensure_csv_intact`, `write_header_if_needed`, `append_to_csv` |
| `processor.py` | `process_input(base_dir) -> stats dict` |
| `extractor.py` | `Extractor(csv_path).extract(key, type_) -> json_str` |

---

## Dependencies

- stdlib: `gzip`, `base64`, `csv`, `json`, `pathlib`, `uuid`, `shutil`
- external: `filelock` (`pip install filelock`)

#!/usr/bin/env python3
"""
Example: loading a "big" CSV into SQLite efficiently.

The techniques that actually matter here, in order of impact:
  1. read in CHUNKS (pd.read_csv(chunksize=...)) -- never hold the
     whole file as one DataFrame, memory stays flat regardless of
     file size.
  2. ONE transaction for the whole load, not one commit per row/chunk
     -- committing is the expensive part, not the inserting.
  3. executemany() per chunk, not a Python-level loop of single
     INSERTs -- one round trip per chunk instead of one per row.
  4. create indexes AFTER the bulk load, not before -- an index
     maintained row-by-row during a big insert is far slower than
     bulk-inserting first and building the index once at the end.

Run: python3 load_csv.py   (after generate_big_csv.py)
"""
import sqlite3
import time
from pathlib import Path

import pandas as pd

from config_loader import db_storage_dir
from csv_typing import normalize_empty_strings, row_to_sqlite_params, type_dataframe

CSV_PATH = db_storage_dir() / "big_sample.csv"
DB_PATH = db_storage_dir() / "big_load.db"
CHUNK_SIZE = 50_000

if not CSV_PATH.exists():
    raise SystemExit(f"{CSV_PATH} not found -- run generate_big_csv.py first")

conn = sqlite3.connect(DB_PATH)

# bulk-load pragmas: durability isn't the point of a disposable example
# db, throughput is -- skip the fsync-per-transaction cost.
conn.execute("PRAGMA journal_mode = WAL")
conn.execute("PRAGMA synchronous = OFF")
conn.execute("PRAGMA temp_store = MEMORY")

conn.execute("DROP TABLE IF EXISTS entries")
conn.execute("""
    CREATE TABLE entries (
        key            TEXT,
        num_value      INTEGER,
        decimal_value  REAL,
        the_date       TEXT,
        the_timestamp  TEXT,
        a_value        TEXT
    )
""")
# no index yet -- added after the load, see below

start = time.perf_counter()
n_rows = 0

conn.execute("BEGIN")
for chunk in pd.read_csv(CSV_PATH, sep=";", encoding="utf-8-sig", dtype=str, chunksize=CHUNK_SIZE):
    chunk = type_dataframe(normalize_empty_strings(chunk))
    rows = [row_to_sqlite_params(r) for r in chunk.itertuples(index=False)]
    conn.executemany("INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?)", rows)
    n_rows += len(rows)
    elapsed = time.perf_counter() - start
    print(f"  loaded {n_rows:,} rows ({n_rows / elapsed:,.0f} rows/sec)")
conn.commit()

load_elapsed = time.perf_counter() - start

# build the index once, now that all rows are in -- much cheaper than
# maintaining it incrementally during the insert loop above.
index_start = time.perf_counter()
conn.execute("CREATE INDEX idx_entries_key ON entries(key)")
conn.commit()
index_elapsed = time.perf_counter() - index_start

print()
print(f"loaded {n_rows:,} rows in {load_elapsed:.2f}s ({n_rows / load_elapsed:,.0f} rows/sec)")
print(f"built index in {index_elapsed:.2f}s")
print(f"-> {DB_PATH}")

conn.close()

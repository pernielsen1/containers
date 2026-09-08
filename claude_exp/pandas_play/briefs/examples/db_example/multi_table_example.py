#!/usr/bin/env python3
"""
Example 2: more than one table in one database.

Pattern: a "load_batches" table tracks each CSV import (when, from
where, how many rows), and "entries" references it via a foreign key.
This is the shape you actually want once you're repeatedly loading
CSVs over time and need to know which batch a row came from.

Run: python3 multi_table_example.py
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config_loader import db_storage_dir
from csv_typing import export_table_to_csv, read_typed_csv, row_to_sqlite_params

HERE = Path(__file__).parent
CSV_PATH = HERE / "sample_data.csv"
DB_PATH = db_storage_dir() / "example_multi.db"

df = read_typed_csv(CSV_PATH)

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA foreign_keys = ON")

conn.execute("DROP TABLE IF EXISTS entries")
conn.execute("DROP TABLE IF EXISTS load_batches")

conn.execute("""
    CREATE TABLE load_batches (
        batch_id     INTEGER PRIMARY KEY AUTOINCREMENT,
        source_file  TEXT NOT NULL,
        loaded_at    TEXT NOT NULL,
        row_count    INTEGER NOT NULL
    )
""")

conn.execute("""
    CREATE TABLE entries (
        batch_id       INTEGER NOT NULL REFERENCES load_batches(batch_id),
        key            TEXT,
        num_value      INTEGER,
        decimal_value  REAL,
        the_date       TEXT,
        the_timestamp  TEXT,
        a_value        TEXT
    )
""")

# --- insert the batch header first, then the rows that belong to it ---
cur = conn.execute(
    "INSERT INTO load_batches (source_file, loaded_at, row_count) VALUES (?, ?, ?)",
    (str(CSV_PATH.name), datetime.now(timezone.utc).isoformat(timespec="seconds"), len(df)),
)
batch_id = cur.lastrowid

rows = [(batch_id, *row_to_sqlite_params(r)) for r in df.itertuples(index=False)]
conn.executemany(
    "INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?, ?)", rows
)
conn.commit()

# simulate a second load of the same file, to show batches accumulate
cur = conn.execute(
    "INSERT INTO load_batches (source_file, loaded_at, row_count) VALUES (?, ?, ?)",
    (str(CSV_PATH.name), datetime.now(timezone.utc).isoformat(timespec="seconds"), len(df)),
)
batch_id_2 = cur.lastrowid
rows_2 = [(batch_id_2, *row_to_sqlite_params(r)) for r in df.itertuples(index=False)]
conn.executemany("INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?, ?)", rows_2)
conn.commit()

print("Batches:")
for r in conn.execute("SELECT * FROM load_batches"):
    print(r)
print()

print("Row count per batch (JOIN + GROUP BY):")
for r in conn.execute("""
    SELECT lb.batch_id, lb.loaded_at, COUNT(*) AS n_rows
    FROM entries e
    JOIN load_batches lb ON lb.batch_id = e.batch_id
    GROUP BY lb.batch_id
    ORDER BY lb.batch_id
"""):
    print(r)
print()

print("Entries from only the most recent batch, with batch metadata attached:")
for r in conn.execute("""
    SELECT e.key, e.num_value, lb.loaded_at
    FROM entries e
    JOIN load_batches lb ON lb.batch_id = e.batch_id
    WHERE lb.batch_id = (SELECT MAX(batch_id) FROM load_batches)
    ORDER BY e.key
"""):
    print(r)


# --- export both tables, Excel-readable: ';' sep, ',' decimal, utf-8-sig ---
export_table_to_csv(conn, "load_batches", HERE / "load_batches_export.csv")
export_table_to_csv(conn, "entries", HERE / "entries_multi_export.csv")
print()
print("Exported 'load_batches' -> load_batches_export.csv")
print("Exported 'entries' -> entries_multi_export.csv")

conn.close()

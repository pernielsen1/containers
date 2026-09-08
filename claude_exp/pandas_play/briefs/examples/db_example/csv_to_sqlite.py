#!/usr/bin/env python3
"""
Example 1: CSV -> single SQLite table, with explicit typing end to end.

Run: python3 csv_to_sqlite.py
"""
import sqlite3  
from pathlib import Path

import pandas as pd

from config_loader import db_storage_dir
from csv_typing import export_table_to_csv, read_typed_csv, row_to_sqlite_params

HERE = Path(__file__).parent
CSV_PATH = HERE / "sample_data.csv"
DB_PATH = db_storage_dir() / "example.db"
EXPORT_PATH = HERE / "entries_export.csv"

df = read_typed_csv(CSV_PATH)

print("Typed frame:")
print(df)
print()
print("dtypes:")
print(df.dtypes)
print()

# --- create the table with an EXPLICIT schema ---
# don't let df.to_sql() infer it -- name every type yourself, same
# discipline as the read step above.
conn = sqlite3.connect(DB_PATH)
conn.execute("DROP TABLE IF EXISTS entries")
conn.execute("""
    CREATE TABLE entries (
        key            TEXT,
        num_value      INTEGER,
        decimal_value  REAL,
        the_date       TEXT,      -- ISO 'YYYY-MM-DD' -- sqlite has no native DATE type
        the_timestamp  TEXT,      -- ISO 'YYYY-MM-DD HH:MM:SS'
        a_value        TEXT
    )
""")

rows = [row_to_sqlite_params(r) for r in df.itertuples(index=False)]
conn.executemany("INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?)", rows)
conn.commit()

print("From SQLite:")
for r in conn.execute("SELECT * FROM entries"):
    print(r)
print()

# these three queries are the whole point: real NULLs vs real zeros,
# and aggregation that just works because the column is a real INTEGER.
print("Sum of num_value (NULLs excluded automatically by SQL):",
      conn.execute("SELECT SUM(num_value) FROM entries").fetchone()[0])

print("Rows where num_value IS NULL:",
      conn.execute("SELECT key FROM entries WHERE num_value IS NULL").fetchall())

print("Rows where num_value = 0 (must NOT be treated as NULL):",
      conn.execute("SELECT key FROM entries WHERE num_value = 0").fetchall())

print("Entries after 2026-01-17, ordered by date (plain string compare works because ISO sorts lexically):",
      conn.execute(
          "SELECT key, the_date FROM entries WHERE the_date > '2026-01-17' ORDER BY the_date"
      ).fetchall())


# --- export back to CSV, Excel-readable: ';' sep, ',' decimal, utf-8-sig ---
export_table_to_csv(conn, "entries", EXPORT_PATH)
print()
print(f"Exported 'entries' -> {EXPORT_PATH.name}")

conn.close()

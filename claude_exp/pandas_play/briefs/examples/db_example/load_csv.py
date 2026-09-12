#!/usr/bin/env python3
"""
Generic CSV -> SQLite loader.

Usage: python3 load_csv.py <infile> <db> <table>

  infile  csv file to load (";" separated, utf-8-sig, header row required)
  db      database name -> stored as db_storage_dir()/<db>.db
  table   table to create and load; dropped first if it already exists

Typing philosophy (same as csv_typing.py): every column is read and
stored as TEXT by default -- no implicit inference, no NaN trap. A
column is only converted if (table, field) is listed in
field_definitions.csv, in which case its "type" there (float,
int/integer, date, datetime/timestamp -- pandas-lingo names) is
applied. This is what lets the same script handle both the small
two-table example below and the big-CSV chunked-load case that used
to be hardcoded here.

Still reads in CHUNKS and commits once at the end -- see the earlier
version of this file (git history) for why that matters on a big CSV.
"""
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd

from config_loader import db_storage_dir
from csv_typing import normalize_empty_strings

HERE = Path(__file__).resolve().parent
FIELD_DEFINITIONS_PATH = HERE / "field_definitions.csv"
CHUNK_SIZE = 50_000

TYPE_CONVERTERS = {
    "float": lambda s: pd.to_numeric(s, errors="raise").astype(float),
    # nullable Int64 keeps missing values as <NA> instead of silently
    # upgrading the whole column to float64 (the "int becomes 1.0" trap).
    "int": lambda s: pd.to_numeric(s, errors="raise").astype("Int64"),
    "integer": lambda s: pd.to_numeric(s, errors="raise").astype("Int64"),
    "date": lambda s: pd.to_datetime(s, errors="raise").dt.strftime("%Y-%m-%d"),
    "datetime": lambda s: pd.to_datetime(s, errors="raise").dt.strftime("%Y-%m-%d %H:%M:%S"),
    "timestamp": lambda s: pd.to_datetime(s, errors="raise").dt.strftime("%Y-%m-%d %H:%M:%S"),
}

SQL_TYPES = {
    "float": "REAL",
    "int": "INTEGER",
    "integer": "INTEGER",
    "date": "TEXT",
    "datetime": "TEXT",
    "timestamp": "TEXT",
}


def load_field_types(table):
    """{field: type} overrides for `table` from field_definitions.csv.
    Fields absent here stay plain str/TEXT -- the default."""
    if not FIELD_DEFINITIONS_PATH.exists():
        return {}
    defs = pd.read_csv(FIELD_DEFINITIONS_PATH, sep=";", encoding="utf-8-sig", dtype=str)
    defs = defs[defs["table"] == table]
    unknown = set(defs["type"]) - set(TYPE_CONVERTERS)
    if unknown:
        raise SystemExit(f"field_definitions.csv: unknown type(s) {unknown} for table {table}")
    return dict(zip(defs["field"], defs["type"]))


def build_create_table_sql(table, columns, field_types):
    cols_sql = ", ".join(f'"{c}" {SQL_TYPES.get(field_types.get(c), "TEXT")}' for c in columns)
    return f'CREATE TABLE "{table}" ({cols_sql})'


def type_chunk(chunk, field_types):
    chunk = normalize_empty_strings(chunk)
    for col, type_name in field_types.items():
        chunk[col] = TYPE_CONVERTERS[type_name](chunk[col])
    return chunk


def chunk_to_params(chunk, columns, field_types):
    int_cols = {c for c, t in field_types.items() if t in ("int", "integer")}
    float_cols = {c for c, t in field_types.items() if t == "float"}
    rows = []
    for values in chunk.itertuples(index=False, name=None):
        row = []
        for col, v in zip(columns, values):
            if pd.isna(v):
                row.append(None)
            elif col in int_cols:
                row.append(int(v))
            elif col in float_cols:
                row.append(float(v))
            else:
                row.append(v)
        rows.append(tuple(row))
    return rows


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: load_csv.py <infile> <db> <table>")
    infile, db, table = sys.argv[1:4]

    csv_path = Path(infile)
    if not csv_path.exists():
        raise SystemExit(f"{csv_path} not found")

    field_types = load_field_types(table)

    columns = list(pd.read_csv(csv_path, sep=";", encoding="utf-8-sig", dtype=str, nrows=0).columns)
    unknown_fields = set(field_types) - set(columns)
    if unknown_fields:
        raise SystemExit(
            f"field_definitions.csv references unknown column(s) {unknown_fields} for table {table}"
        )

    db_path = db_storage_dir() / (db if db.endswith(".db") else f"{db}.db")
    conn = sqlite3.connect(db_path)

    conn.execute(f'DROP TABLE IF EXISTS "{table}"')
    conn.execute(build_create_table_sql(table, columns, field_types))

    insert_sql = f'INSERT INTO "{table}" VALUES ({", ".join("?" for _ in columns)})'

    start = time.perf_counter()
    n_rows = 0
    conn.execute("BEGIN")
    for chunk in pd.read_csv(csv_path, sep=";", encoding="utf-8-sig", dtype=str, chunksize=CHUNK_SIZE):
        chunk = type_chunk(chunk, field_types)
        rows = chunk_to_params(chunk, columns, field_types)
        conn.executemany(insert_sql, rows)
        n_rows += len(rows)
    conn.commit()
    elapsed = time.perf_counter() - start

    print(f"loaded {n_rows:,} rows into {db_path}::{table} in {elapsed:.2f}s")
    conn.close()


if __name__ == "__main__":
    main()

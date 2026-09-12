#!/usr/bin/env python3
"""
Generic file -> SQLite table loader (csv or xlsx).

Usage: python3 load_table.py <infile> <db> <table> [--sheet NAME] (--env prod|test | --config PATH)

  infile   csv or xlsx file to load; format is picked from the
           extension (.csv -- ";" separated, utf-8-sig, header row
           required; .xlsx/.xls -- read via pandas/openpyxl)
  db       database name -> stored as db_storage_dir()/<db>.db
  table    table to create and load; dropped first if it already exists
  --sheet  xlsx only: sheet name to read (default: first sheet)
  --env    normal mode: prod or test -> db_example/<env>/config.json
  --config explicit config.json path -- overrides --env, for anything
           outside prod/test (e.g. samples/config.json)

Typing philosophy (same as csv_typing.py): every column is read and
stored as TEXT by default -- no implicit inference, no NaN trap. A
column is only converted if (table, field) is listed in
field_definitions.csv, in which case its "type" there (float,
int/integer, date, datetime/timestamp -- pandas-lingo names) is
applied. This is what lets the same script handle both the small
two-table example below and the big-CSV chunked-load case that used
to be hardcoded here.

CSV still reads in CHUNKS and commits once at the end -- see git
history for why that matters on a big CSV. xlsx has no chunked reader
in pandas, so it's read whole -- fine in practice, Excel files aren't
the "large CSV" case this was built for.
"""
import argparse
import logging
import sqlite3
import time
from pathlib import Path

import pandas as pd

from config_loader import config_path_for_env, db_storage_dir
from csv_typing import normalize_empty_strings

HERE = Path(__file__).resolve().parent
FIELD_DEFINITIONS_PATH = HERE / "field_definitions.csv"
CHUNK_SIZE = 50_000

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

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


def read_chunks_and_columns(infile_path, suffix, sheet):
    """Return (columns, chunk_iterable). CSV stays lazily chunked (memory
    stays flat on a big file); xlsx has no chunked reader in pandas so
    it's read whole into a single-item list instead."""
    if suffix == ".csv":
        if sheet:
            raise SystemExit("--sheet only applies to .xlsx input")
        columns = list(
            pd.read_csv(infile_path, sep=";", encoding="utf-8-sig", dtype=str, nrows=0).columns
        )
        chunks = pd.read_csv(infile_path, sep=";", encoding="utf-8-sig", dtype=str, chunksize=CHUNK_SIZE)
        return columns, chunks

    sheet_name = sheet if sheet else 0
    full_df = pd.read_excel(infile_path, sheet_name=sheet_name, dtype=str)
    return list(full_df.columns), [full_df]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("infile")
    parser.add_argument("db")
    parser.add_argument("table")
    parser.add_argument("--sheet", help="xlsx only: sheet name (default: first sheet)")
    parser.add_argument("--env", choices=["prod", "test"], help="normal mode: db_example/<env>/config.json")
    parser.add_argument("--config", help="explicit config.json path -- overrides --env")
    args = parser.parse_args()

    if not args.env and not args.config:
        raise SystemExit("pass --env prod|test (or --config <path> to override)")
    config_path = args.config if args.config else config_path_for_env(args.env)

    infile_path = Path(args.infile)
    if not infile_path.exists():
        raise SystemExit(f"{infile_path} not found")

    suffix = infile_path.suffix.lower()
    if suffix not in (".csv", ".xlsx", ".xls"):
        raise SystemExit(f"unsupported file type '{suffix}' -- expected .csv or .xlsx")

    db_path = db_storage_dir(config_path) / (args.db if args.db.endswith(".db") else f"{args.db}.db")
    logger.info("loading %s -> db=%s table=%s", infile_path, db_path, args.table)

    field_types = load_field_types(args.table)
    columns, chunks = read_chunks_and_columns(infile_path, suffix, args.sheet)

    unknown_fields = set(field_types) - set(columns)
    if unknown_fields:
        raise SystemExit(
            f"field_definitions.csv references unknown column(s) {unknown_fields} for table {args.table}"
        )

    conn = sqlite3.connect(db_path)

    conn.execute(f'DROP TABLE IF EXISTS "{args.table}"')
    conn.execute(build_create_table_sql(args.table, columns, field_types))

    insert_sql = f'INSERT INTO "{args.table}" VALUES ({", ".join("?" for _ in columns)})'

    start = time.perf_counter()
    n_rows = 0
    conn.execute("BEGIN")
    for chunk in chunks:
        chunk = type_chunk(chunk, field_types)
        rows = chunk_to_params(chunk, columns, field_types)
        conn.executemany(insert_sql, rows)
        n_rows += len(rows)
    conn.commit()
    elapsed = time.perf_counter() - start

    logger.info("loaded %s rows into %s::%s in %.2fs", f"{n_rows:,}", db_path, args.table, elapsed)
    conn.close()


if __name__ == "__main__":
    main()

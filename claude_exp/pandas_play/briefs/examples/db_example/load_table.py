#!/usr/bin/env python3
"""
Generic file -> SQLite table loader (csv or xlsx).

Usage: python3 load_table.py <infile> <db> <table> [--sheet NAME]
           [--encoding ENC] [--delimiter CHAR] [--decimal CHAR]
           (--env prod|test | --config PATH)

  infile   csv or xlsx file to load; format is picked from the
           extension (.csv -- ";" separated, utf-8-sig, header row
           required; .xlsx/.xls -- read via pandas/openpyxl)
  db       database name -> stored as db_storage_dir()/<db>.db
  table    table to create and load; dropped first if it already exists
  --sheet  xlsx only: sheet name to read (default: first sheet)
  --encoding   csv only: file encoding (default utf-8-sig -- reads plain
           utf-8 identically and also strips the BOM Excel adds)
  --delimiter  csv only: one-character field separator (default ";").
           Also takes a name instead of a character -- see
           DELIMITER_ALIASES -- e.g. "tab" or "semi_colon"; handy for
           PRAGMA load_table (see run_sql.py) where a literal ';'
           can't be written since statements are themselves split on
           a bare ';'.
  --decimal    csv only: decimal separator used in float columns
           (default ","; a "." in the data is accepted too unless you
           pass --decimal . explicitly, then "1,5" is an error)
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

field_definitions.csv also has an optional "sql_column_name" column:
when set on a row, the table column is created and loaded under that
name instead of the source field's own name -- e.g. import a column
called "num_value" but store it as "amount". Only usable together
with a real type conversion (a row always needs a "type"); there's no
rename-only row for a column that stays plain str.

CSV still reads in CHUNKS and commits once at the end -- see git
history for why that matters on a big CSV. xlsx has no chunked reader
in pandas, so it's read whole -- fine in practice, Excel files aren't
the "large CSV" case this was built for.

The actual load lives on the TableLoader class below, working against
an already-open connection -- main() is a thin CLI wrapper around it
(resolve config -> open connection -> TableLoader().load(...)). This
is also what run_sql.py's PRAGMA load_table uses: it builds ONE
TableLoader for the whole script run and reuses it across every
PRAGMA load_table in that script, so field_definitions.csv is read
once and cached rather than re-read on every load.
"""
import argparse
import logging
import shlex
import sqlite3
import time
from pathlib import Path

import pandas as pd

from config_loader import config_path_for_env, db_storage_dir
from csv_typing import normalize_empty_strings

HERE = Path(__file__).resolve().parent
FIELD_DEFINITIONS_PATH = HERE / "field_definitions.csv"
CHUNK_SIZE = 50_000
DEFAULT_ENCODING = "utf-8-sig"
DEFAULT_DELIMITER = ";"
DEFAULT_DECIMAL = ","

# Named spellings for a delimiter, on top of a literal character --
# case-insensitive. "\t" (backslash-t) also still works, kept for
# people typing it that way already; these exist mainly so ';' has a
# way to be written that doesn't collide with run_sql.py splitting
# statements on a bare ';' (PRAGMA load_table = '... --delimiter ;';
# would be truncated mid-statement -- 'semi_colon' isn't).
DELIMITER_ALIASES = {
    "comma": ",",
    "semicolon": ";",
    "semi_colon": ";",
    "tab": "\t",
    "pipe": "|",
    "space": " ",
}

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


def resolve_delimiter(value):
    """A literal one-character separator, a DELIMITER_ALIASES name
    (case-insensitive), or the legacy "\\t" spelling -- in that order."""
    alias = DELIMITER_ALIASES.get(value.lower())
    if alias is not None:
        return alias
    return value.replace("\\t", "\t")


def build_create_table_sql(table, columns, field_types, column_renames):
    sql_names = [column_renames.get(c, c) for c in columns]
    duplicates = {n for n in sql_names if sql_names.count(n) > 1}
    if duplicates:
        raise SystemExit(f"field_definitions.csv: sql_column_name collision on {duplicates} for table {table}")
    cols_sql = ", ".join(
        f'"{name}" {SQL_TYPES.get(field_types.get(c), "TEXT")}' for c, name in zip(columns, sql_names)
    )
    return f'CREATE TABLE "{table}" ({cols_sql})'


def type_chunk(chunk, field_types, decimal="."):
    chunk = normalize_empty_strings(chunk)
    for col, type_name in field_types.items():
        values = chunk[col]
        # data is read as str, so pandas' own decimal= never applies;
        # normalise the separator to "." before numeric conversion.
        if type_name == "float" and decimal != ".":
            values = values.str.replace(decimal, ".", regex=False)
        chunk[col] = TYPE_CONVERTERS[type_name](values)
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


def read_chunks_and_columns(infile_path, suffix, sheet, encoding=DEFAULT_ENCODING, delimiter=DEFAULT_DELIMITER):
    """Return (columns, chunk_iterable). CSV stays lazily chunked (memory
    stays flat on a big file); xlsx has no chunked reader in pandas so
    it's read whole into a single-item list instead."""
    if suffix == ".csv":
        if sheet:
            raise SystemExit("--sheet only applies to .xlsx input")
        columns = list(
            pd.read_csv(infile_path, sep=delimiter, encoding=encoding, dtype=str, nrows=0).columns
        )
        chunks = pd.read_csv(infile_path, sep=delimiter, encoding=encoding, dtype=str, chunksize=CHUNK_SIZE)
        return columns, chunks

    sheet_name = sheet if sheet else 0
    full_df = pd.read_excel(infile_path, sheet_name=sheet_name, dtype=str)
    return list(full_df.columns), [full_df]


def add_load_options(parser):
    """--sheet/--encoding/--delimiter/--decimal, shared between the CLI
    parser (main(), below) and the PRAGMA load_table mini-parser
    (run_sql.py) so the two never drift apart on flag names/help text."""
    parser.add_argument("--sheet", help="xlsx only: sheet name (default: first sheet)")
    parser.add_argument("--encoding", help=f"csv only: file encoding (default {DEFAULT_ENCODING})")
    parser.add_argument(
        "--delimiter",
        help=f'csv only: one character, or a name from DELIMITER_ALIASES (default "{DEFAULT_DELIMITER}")',
    )
    parser.add_argument("--decimal", help=f'csv only: decimal separator in float columns (default "{DEFAULT_DECIMAL}")')
    return parser


def build_pragma_parser():
    """infile + table positionals, no db selection (PRAGMA load_table
    runs on run_sql.py's already-open connection)."""
    parser = argparse.ArgumentParser(prog="PRAGMA load_table", add_help=False)
    parser.add_argument("infile")
    parser.add_argument("table")
    return add_load_options(parser)


class TableLoader:
    """Loads a csv/xlsx file into a table on an already-open sqlite3
    connection. One instance can be reused across several .load() calls
    (different tables, even different files) -- field_definitions.csv is
    read once, lazily, on first use, and cached for the rest."""

    def __init__(self, field_definitions_path=None):
        self.field_definitions_path = Path(field_definitions_path) if field_definitions_path else FIELD_DEFINITIONS_PATH
        self._field_defs_cache = None  # None = not loaded yet; pd.DataFrame or False (file absent) after

    def _read_field_definitions(self):
        if not self.field_definitions_path.exists():
            return False
        return pd.read_csv(
            self.field_definitions_path, sep=";", encoding="utf-8-sig", dtype=str, keep_default_na=False
        )

    def _field_defs_for(self, table):
        """(field_types, column_renames) for `table` -- see module
        docstring for the field_definitions.csv format."""
        if self._field_defs_cache is None:
            self._field_defs_cache = self._read_field_definitions()
        if self._field_defs_cache is False:
            return {}, {}
        defs = self._field_defs_cache
        defs = defs[defs["table"] == table]
        unknown = set(defs["type"]) - set(TYPE_CONVERTERS)
        if unknown:
            raise SystemExit(f"{self.field_definitions_path.name}: unknown type(s) {unknown} for table {table}")
        field_types = dict(zip(defs["field"], defs["type"]))
        column_renames = {}
        if "sql_column_name" in defs.columns:
            column_renames = {
                field: name for field, name in zip(defs["field"], defs["sql_column_name"]) if name
            }
        return field_types, column_renames

    def load(self, conn, infile, table, sheet=None, encoding=None, delimiter=None, decimal=None):
        """Drop `table` if it exists, create it, load infile into it.
        Returns the number of rows loaded. Does not commit or close conn
        -- the caller owns the connection's lifecycle."""
        infile_path = Path(infile)
        if not infile_path.exists():
            raise SystemExit(f"{infile_path} not found")

        suffix = infile_path.suffix.lower()
        if suffix not in (".csv", ".xlsx", ".xls"):
            raise SystemExit(f"unsupported file type '{suffix}' -- expected .csv or .xlsx")

        if suffix == ".csv":
            enc = encoding or DEFAULT_ENCODING
            delim = DEFAULT_DELIMITER if delimiter is None else resolve_delimiter(delimiter)
            dec = DEFAULT_DECIMAL if decimal is None else decimal
            if len(delim) != 1:
                raise SystemExit(f"--delimiter must be one character, \\t, or a name from DELIMITER_ALIASES, got '{delimiter}'")
            if len(dec) != 1:
                raise SystemExit(f"--decimal must be one character, got '{decimal}'")
        else:
            for name, val in (("encoding", encoding), ("delimiter", delimiter), ("decimal", decimal)):
                if val is not None:
                    raise SystemExit(f"--{name} only applies to .csv input")
            enc, delim, dec = DEFAULT_ENCODING, DEFAULT_DELIMITER, "."

        logger.info("loading %s -> table=%s", infile_path, table)

        field_types, column_renames = self._field_defs_for(table)
        columns, chunks = read_chunks_and_columns(infile_path, suffix, sheet, enc, delim)

        unknown_fields = (set(field_types) | set(column_renames)) - set(columns)
        if unknown_fields:
            raise SystemExit(
                f"{self.field_definitions_path.name} references unknown column(s) {unknown_fields} for table {table}"
            )

        conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        conn.execute(build_create_table_sql(table, columns, field_types, column_renames))
        insert_sql = f'INSERT INTO "{table}" VALUES ({", ".join("?" for _ in columns)})'

        start = time.perf_counter()
        n_rows = 0
        conn.execute("BEGIN")
        for chunk in chunks:
            chunk = type_chunk(chunk, field_types, dec)
            rows = chunk_to_params(chunk, columns, field_types)
            conn.executemany(insert_sql, rows)
            n_rows += len(rows)
        conn.commit()
        elapsed = time.perf_counter() - start

        logger.info("loaded %s rows into %s in %.2fs", f"{n_rows:,}", table, elapsed)
        return n_rows

    def load_from_pragma(self, conn, base_dir, value):
        """Parse the PRAGMA load_table = '...' payload -- same flags as
        the CLI (infile table [--sheet ...] [--encoding ...]
        [--delimiter ...] [--decimal ...]), infile resolved relative to
        base_dir (the .sql file that wrote the directive) -- and load
        it. Used by run_sql.py."""
        args = build_pragma_parser().parse_args(shlex.split(value))
        infile_path = (Path(base_dir) / args.infile).expanduser()
        return self.load(
            conn, infile_path, args.table,
            sheet=args.sheet, encoding=args.encoding, delimiter=args.delimiter, decimal=args.decimal,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("infile")
    parser.add_argument("db")
    parser.add_argument("table")
    add_load_options(parser)
    parser.add_argument("--env", choices=["prod", "test"], help="normal mode: db_example/<env>/config.json")
    parser.add_argument("--config", help="explicit config.json path -- overrides --env")
    args = parser.parse_args()

    if not args.env and not args.config:
        raise SystemExit("pass --env prod|test (or --config <path> to override)")
    config_path = args.config if args.config else config_path_for_env(args.env)

    db_path = db_storage_dir(config_path) / (args.db if args.db.endswith(".db") else f"{args.db}.db")
    conn = sqlite3.connect(db_path)
    TableLoader().load(
        conn, args.infile, args.table,
        sheet=args.sheet, encoding=args.encoding, delimiter=args.delimiter, decimal=args.decimal,
    )
    conn.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
run_sql.py <sql-script> [--db generic_example] [--output out.csv] (--env prod|test | --config PATH)

Runs every ';'-separated statement in sql-script against
db_storage_dir()/<db>.db (same ".db" naming as load_table.py). Comments
use sqlite's own '--' syntax. A statement of the form

    PRAGMA export = 'path/to/file.csv';   -- or .xlsx

is a script-level directive, not real SQL: run_sql.py intercepts it
instead of sending it to sqlite and writes the LAST result set (from
the most recent SELECT) to that path -- format picked from the
extension. Since PRAGMA is real SQL syntax and sqlite silently no-ops
any pragma name it doesn't recognise, the script stays valid to run
with a plain sqlite3 client too. UDFs from udf_definitions.csv are always
registered (see run_sql_udf.py); a second directive

    PRAGMA udf_extra = 'my_udfs.csv';   -- path relative to the sql script

adds that csv's UDFs for this script only. --output works the same way from the
command line for the final result set. --env is the normal way to
pick prod/test; --config overrides it with an explicit config.json
path (e.g. samples/config.json).
"""
import argparse
import re
import sqlite3
from pathlib import Path

import pandas as pd

from config_loader import config_path_for_env, db_storage_dir
from run_sql_udf import DEFAULT_UDF_CSV, register_udfs

EXPORT_PRAGMA_RE = re.compile(r"^PRAGMA\s+export\s*=\s*'([^']+)'$", re.IGNORECASE)
UDF_EXTRA_PRAGMA_RE = re.compile(r"^PRAGMA\s+udf_extra\s*=\s*'([^']+)'$", re.IGNORECASE)


def directive_text(stmt):
    """stmt minus leading '--' comment lines, so a comment block above a
    PRAGMA directive doesn't stop it matching."""
    lines = stmt.splitlines()
    while lines and (not lines[0].strip() or lines[0].lstrip().startswith("--")):
        lines.pop(0)
    return "\n".join(lines).strip()


def split_statements(sql_text):
    return [s.strip() for s in sql_text.split(";") if s.strip()]


def write_result(df, path):
    """Write df to path as csv or xlsx, picked from the file extension."""
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        df.to_csv(path, sep=";", decimal=",", index=False, encoding="utf-8-sig")
    elif suffix == ".xlsx":
        df.to_excel(path, index=False)
    else:
        raise SystemExit(f"export: unsupported file extension '{suffix}' (use .csv or .xlsx) -- {path}")
    print(f"wrote {len(df)} rows -> {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("sql_script")
    parser.add_argument("--db", default="download")
    parser.add_argument("--output")
    parser.add_argument("--env", choices=["prod", "test"], help="normal mode: db_example/<env>/config.json")
    parser.add_argument("--config", help="explicit config.json path -- overrides --env")
    args = parser.parse_args()

    if not args.env and not args.config:
        raise SystemExit("pass --env prod|test (or --config <path> to override)")
    config_path = args.config if args.config else config_path_for_env(args.env)

    script_path = Path(args.sql_script)
    if not script_path.exists():
        raise SystemExit(f"{script_path} not found")

    statements = split_statements(script_path.read_text(encoding="utf-8"))
    if not statements:
        raise SystemExit(f"{script_path} contains no sql statements")

    db_path = db_storage_dir(config_path) / (args.db if args.db.endswith(".db") else f"{args.db}.db")
    conn = sqlite3.connect(db_path)

    # UDFs must exist before any statement runs, so udf_extra pragmas are
    # pre-scanned (their position in the script doesn't matter).
    register_udfs(conn, DEFAULT_UDF_CSV)
    for stmt in statements:
        udf_match = UDF_EXTRA_PRAGMA_RE.match(directive_text(stmt))
        if udf_match:
            register_udfs(conn, script_path.resolve().parent / udf_match.group(1))

    result_df = None
    last_cursor = None
    for stmt in statements:
        if UDF_EXTRA_PRAGMA_RE.match(directive_text(stmt)):
            continue
        export_match = EXPORT_PRAGMA_RE.match(directive_text(stmt))
        if export_match:
            if result_df is None:
                raise SystemExit(f"PRAGMA export: no result set to export -- {stmt}")
            write_result(result_df, export_match.group(1))
            continue
        cursor = conn.execute(stmt)
        last_cursor = cursor
        # non-SELECT statements (CREATE/INSERT/UPDATE/...) have no
        # cursor.description -- only a SELECT's result carries forward.
        if cursor.description is not None:
            columns = [d[0] for d in cursor.description]
            result_df = pd.DataFrame(cursor.fetchall(), columns=columns)
        else:
            result_df = None
    conn.commit()
    conn.close()

    if args.output:
        if result_df is None:
            raise SystemExit("last statement produced no result set -- nothing to write to --output")
        write_result(result_df, args.output)
    elif result_df is not None:
        # SQL NULL becomes NaN/None once fetchall()'s rows go into a
        # DataFrame (pandas upcasts an int/float column with a missing
        # value to float64+NaN) -- fillna('') displays it as blank,
        # same as NULL means nothing, not the literal text "NaN".
        print(result_df.fillna("").to_string(index=False))
    elif last_cursor.rowcount >= 0:
        # last statement was an action query (INSERT/UPDATE/DELETE),
        # not a SELECT -- nothing to display, but say so rather than
        # exiting silently. rowcount is -1 for DDL (CREATE/DROP/...),
        # where "rows affected" isn't a meaningful concept.
        print(f"no result set (action query) -- {last_cursor.rowcount} row(s) affected")
    else:
        print("no result set (action query)")


if __name__ == "__main__":
    main()

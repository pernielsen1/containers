#!/usr/bin/env python3
"""
run_sql.py <sql-script> [--db generic_example] [--output out.csv] (--env prod|test | --config PATH)

Runs every ';'-separated statement in sql-script against
db_storage_dir()/<db>.db (same ".db" naming as load_table.py). A line
whose first non-blank character is '#' is a script-level comment and
is dropped before execution -- sqlite's own '--' comment syntax still
works too, unaffected. If
--output is given, the result set of the LAST statement (expected to
be a SELECT) is written there as csv -- ';' separator, ',' decimal,
utf-8-sig, same convention as the rest of this example. --env is the
normal way to pick prod/test; --config overrides it with an explicit
config.json path (e.g. samples/config.json).
"""
import argparse
import sqlite3
from pathlib import Path

import pandas as pd

from config_loader import config_path_for_env, db_storage_dir


def strip_comment_lines(sql_text):
    """Drop any line whose first non-blank character is '#' -- a
    script-level comment, not SQL (sqlite's own comment syntax is
    '--', which this leaves untouched and passes straight to sqlite)."""
    return "\n".join(line for line in sql_text.splitlines() if not line.lstrip().startswith("#"))


def split_statements(sql_text):
    sql_text = strip_comment_lines(sql_text)
    return [s.strip() for s in sql_text.split(";") if s.strip()]


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

    result_df = None
    last_cursor = None
    for stmt in statements:
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
        result_df.to_csv(args.output, sep=";", decimal=",", index=False, encoding="utf-8-sig")
        print(f"wrote {len(result_df)} rows -> {args.output}")
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

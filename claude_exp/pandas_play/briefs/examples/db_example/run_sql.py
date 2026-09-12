#!/usr/bin/env python3
"""
run_sql.py <sql-script> [--db generic_example] [--output out.csv]

Runs every ';'-separated statement in sql-script against
db_storage_dir()/<db>.db (same "generic_example" default and ".db"
naming as load_table.py). If --output is given, the result set of the
LAST statement (expected to be a SELECT) is written there as csv --
';' separator, ',' decimal, utf-8-sig, same convention as the rest of
this example.
"""
import argparse
import sqlite3
from pathlib import Path

import pandas as pd

from config_loader import db_storage_dir


def split_statements(sql_text):
    return [s.strip() for s in sql_text.split(";") if s.strip()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("sql_script")
    parser.add_argument("--db", default="generic_example")
    parser.add_argument("--output")
    args = parser.parse_args()

    script_path = Path(args.sql_script)
    if not script_path.exists():
        raise SystemExit(f"{script_path} not found")

    statements = split_statements(script_path.read_text(encoding="utf-8"))
    if not statements:
        raise SystemExit(f"{script_path} contains no sql statements")

    db_path = db_storage_dir() / (args.db if args.db.endswith(".db") else f"{args.db}.db")
    conn = sqlite3.connect(db_path)

    result_df = None
    for stmt in statements:
        cursor = conn.execute(stmt)
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


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
create_sp.py -- SQLite has no persistent stored procedures (no
CREATE PROCEDURE). The nearest equivalent is a Python function
registered on a connection via sqlite3.Connection.create_function().
That registration is connection-scoped, not saved in the .db file --
it's invisible to the plain `sqlite3` CLI, run_sql.py, or any other
process/connection. So this script both registers my_upper and
immediately demonstrates it in a SELECT, since that's the only way to
show it "in use" at all.

create_function dispatches by argument COUNT, not one fixed signature
-- the same SQL name can be registered multiple times at different
arities, and SQLite calls whichever Python function matches how many
arguments appear at the call site. Demonstrated here with three
arities of "my_upper":
  my_upper(name)                    -> UPPER(name)
  my_upper(name, const)             -> const + '_' + UPPER(name)
  my_upper(const, name, name)       -> const + '_' + UPPER(name) + '_' + LOWER(name)

Usage: python3 create_sp.py (--env prod|test | --config PATH) [--db download]
"""
import argparse
import sqlite3

from config_loader import config_path_for_env, db_storage_dir


def my_upper_1(name):
    return None if name is None else name.upper()


def my_upper_2(name, const):
    return None if name is None else f"{const}_{name.upper()}"


def my_upper_3(const, name_a, name_b):
    if name_a is None or name_b is None:
        return None
    return f"{const}_{name_a.upper()}_{name_b.lower()}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", choices=["prod", "test"], help="normal mode: db_example/<env>/config.json")
    parser.add_argument("--config", help="explicit config.json path -- overrides --env")
    parser.add_argument("--db", default="download")
    args = parser.parse_args()

    if not args.env and not args.config:
        raise SystemExit("pass --env prod|test (or --config <path> to override)")
    config_path = args.config if args.config else config_path_for_env(args.env)

    db_path = db_storage_dir(config_path) / (args.db if args.db.endswith(".db") else f"{args.db}.db")
    conn = sqlite3.connect(db_path)
    conn.create_function("my_upper", 1, my_upper_1)
    conn.create_function("my_upper", 2, my_upper_2)
    conn.create_function("my_upper", 3, my_upper_3)

    print(f"registered my_upper/1, /2, /3 on {db_path} (connection-scoped, see module docstring)")

    queries = [
        "SELECT a_key, name, my_upper(name) AS name_upper FROM a_cust ORDER BY a_key",
        "SELECT a_key, name, my_upper(name, '42') AS name_upper FROM a_cust ORDER BY a_key",
        "SELECT a_key, name, my_upper('42', name, name) AS name_upper FROM a_cust ORDER BY a_key",
    ]
    for sql in queries:
        print()
        print(sql + ";")
        for row in conn.execute(sql):
            print(row)

    conn.close()


if __name__ == "__main__":
    main()

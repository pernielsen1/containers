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

    PRAGMA udf_extra = 'my_udfs.csv';   -- path relative to the file it's in

adds that csv's UDFs for this script only. A third directive

    PRAGMA include = 'shared.sql';      -- path relative to the file it's in

splices that script's statements in at that point (recursively, cycles
rejected) -- lets a "mother script" reuse shared setup (views,
formatting) from one place while keeping its own PRAGMA export calls.
A fourth directive

    PRAGMA load_table = 'infile.csv table_name --delimiter , --decimal .';

loads a csv/xlsx into a table on this script's own connection --
same flags as load_table.py's CLI (minus db selection, since the
connection already exists), parsed the same way a shell would split
them; infile is resolved relative to the file the directive is in. A
fifth directive

    PRAGMA print = 'now open out.csv and check the totals';

prints the message to the console right then -- an instruction for
whoever is watching the run, e.g. a manual next step. --output works
the same way from the
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
from load_table import TableLoader

EXPORT_PRAGMA_RE = re.compile(r"^PRAGMA\s+export\s*=\s*'([^']+)'$", re.IGNORECASE)
UDF_EXTRA_PRAGMA_RE = re.compile(r"^PRAGMA\s+udf_extra\s*=\s*'([^']+)'$", re.IGNORECASE)
INCLUDE_PRAGMA_RE = re.compile(r"^PRAGMA\s+include\s*=\s*'([^']+)'$", re.IGNORECASE)
LOAD_TABLE_PRAGMA_RE = re.compile(r"^PRAGMA\s+load_table\s*=\s*'([^']+)'$", re.IGNORECASE)
PRINT_PRAGMA_RE = re.compile(r"^PRAGMA\s+print\s*=\s*'([^']+)'$", re.IGNORECASE)


def directive_text(stmt):
    """stmt minus leading '--' comment lines, so a comment block above a
    PRAGMA directive doesn't stop it matching."""
    lines = stmt.splitlines()
    while lines and (not lines[0].strip() or lines[0].lstrip().startswith("--")):
        lines.pop(0)
    return "\n".join(lines).strip()


def split_statements(sql_text):
    return [s.strip() for s in sql_text.split(";") if s.strip()]


def read_statements(script_path, _chain=()):
    """(stmt, source_path) pairs for script_path, with PRAGMA include
    statements recursively replaced by the included script's own
    statements (so execution order and udf_extra/export still work
    from wherever they're actually written). _chain is the include
    path leading here, used only to reject a cycle."""
    script_path = script_path.resolve()
    if script_path in _chain:
        trail = " -> ".join(str(p) for p in (*_chain, script_path))
        raise SystemExit(f"PRAGMA include cycle detected: {trail}")
    if not script_path.exists():
        raise SystemExit(f"{script_path} not found")

    statements = []
    for stmt in split_statements(script_path.read_text(encoding="utf-8")):
        include_match = INCLUDE_PRAGMA_RE.match(directive_text(stmt))
        if include_match:
            included_path = script_path.parent / include_match.group(1)
            statements.extend(read_statements(included_path, (*_chain, script_path)))
        else:
            statements.append((stmt, script_path))
    return statements


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

    # includes are expanded first -- statements is (stmt, source_path)
    # pairs, source_path being whichever file actually wrote that
    # statement (the mother script or one it included), so a later
    # relative udf_extra path resolves against the right directory.
    statements = read_statements(script_path)
    if not statements:
        raise SystemExit(f"{script_path} contains no sql statements")

    db_path = db_storage_dir(config_path) / (args.db if args.db.endswith(".db") else f"{args.db}.db")
    conn = sqlite3.connect(db_path)

    # UDFs must exist before any statement runs, so udf_extra pragmas are
    # pre-scanned (their position in the script doesn't matter).
    register_udfs(conn, DEFAULT_UDF_CSV)
    for stmt, source_path in statements:
        udf_match = UDF_EXTRA_PRAGMA_RE.match(directive_text(stmt))
        if udf_match:
            register_udfs(conn, source_path.parent / udf_match.group(1))

    # one TableLoader for the whole run -- PRAGMA load_table calls share
    # it, so field_definitions.csv is read once and cached, not per call.
    table_loader = TableLoader()

    result_df = None
    last_cursor = None
    for stmt, source_path in statements:
        if UDF_EXTRA_PRAGMA_RE.match(directive_text(stmt)):
            continue
        export_match = EXPORT_PRAGMA_RE.match(directive_text(stmt))
        if export_match:
            if result_df is None:
                raise SystemExit(f"PRAGMA export: no result set to export -- {stmt}")
            write_result(result_df, export_match.group(1))
            continue
        load_table_match = LOAD_TABLE_PRAGMA_RE.match(directive_text(stmt))
        if load_table_match:
            # not a query -- doesn't touch result_df/last_cursor, same
            # as export above just reads them rather than setting them.
            table_loader.load_from_pragma(conn, source_path.parent, load_table_match.group(1))
            continue
        print_match = PRINT_PRAGMA_RE.match(directive_text(stmt))
        if print_match:
            print(print_match.group(1))
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

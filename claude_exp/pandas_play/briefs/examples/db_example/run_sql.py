#!/usr/bin/env python3
"""
run_sql.py <sql-script> [--db generic_example] [--output out.csv] (--env prod|test | --config PATH)

Runs every ';'-separated statement in sql-script against
db_storage_dir()/<db>.db (same ".db" naming as load_table.py). Comments
use sqlite's own '--' syntax. A statement of the form

    PRAGMA export = 'path/to/file.csv';   -- or .xlsx
    PRAGMA export = 'path/to/file.xlsx --sheet Totals';

is a script-level directive, not real SQL: run_sql.py intercepts it
instead of sending it to sqlite and writes the LAST result set (from
the most recent SELECT) to that path -- format picked from the
extension. --sheet is xlsx only: a plain export (no --sheet) overwrites
the whole file each time, same as always; naming a sheet instead
appends that sheet to the workbook at that path, so several PRAGMA
export calls in one run -- including from an included child script --
can build up one workbook with several sheets. The same path+sheet
twice in one run is an error, not a silent overwrite. Since PRAGMA is
real SQL syntax and sqlite silently no-ops any pragma name it doesn't
recognise, the script stays valid to run with a plain sqlite3 client
too. A statement that's entirely a '--' comment (once any comment
lines are stripped, nothing is left) is skipped rather than sent to
sqlite -- so commenting out the last real line of a script doesn't
erase the result set that would otherwise have been shown/exported.
UDFs from udf_definitions.csv are always
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
whoever is watching the run, e.g. a manual next step. A sixth directive

    PRAGMA show_result = 'off';         -- or 'on' (the default)

stops the last result set (or the "no result set" line) being shown
on the console at the end of the run -- for scripts in a production
stream, where it's noise. Position doesn't matter; print/export
messages and --output are unaffected. Only honoured in the top-level
script -- inside an included file it's ignored, so a shared include
can't silently switch output off for every script using it.
--output works the same way from the
command line for the final result set. --env is the normal way to
pick prod/test; --config overrides it with an explicit config.json
path (e.g. samples/config.json).
"""
import argparse
import re
import shlex
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
SHOW_RESULT_PRAGMA_RE = re.compile(r"^PRAGMA\s+show_result\s*=\s*'([^']+)'$", re.IGNORECASE)


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


def build_export_pragma_parser():
    """path positional + --sheet, xlsx only (see write_result)."""
    parser = argparse.ArgumentParser(prog="PRAGMA export", add_help=False)
    parser.add_argument("path")
    parser.add_argument("--sheet", help="xlsx only: sheet name -- repeat PRAGMA export with a "
                         "different --sheet for the same path to add sheets to one workbook "
                         "(default: overwrite the whole file each time, like plain export)")
    return parser


def write_result(df, path, sheet=None, xlsx_sheets=None):
    """Write df to path as csv or xlsx, picked from the file extension.
    xlsx_sheets tracks, for this run, which (resolved path, sheet name)
    pairs have already been written -- so a second PRAGMA export with a
    different --sheet for the same path appends a sheet to that workbook
    instead of overwriting it, and a repeated --sheet name is caught as
    a mistake rather than silently losing the earlier sheet."""
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        if sheet is not None:
            raise SystemExit(f"PRAGMA export: --sheet is xlsx only -- {path}")
        df.to_csv(path, sep=";", decimal=",", index=False, encoding="utf-8-sig")
        print(f"wrote {len(df)} rows -> {path}")
    elif suffix == ".xlsx":
        if sheet is None:
            df.to_excel(path, index=False)
            print(f"wrote {len(df)} rows -> {path}")
        else:
            resolved = Path(path).resolve()
            sheets_done = xlsx_sheets.setdefault(resolved, set())
            if sheet in sheets_done:
                raise SystemExit(f"PRAGMA export: sheet '{sheet}' already written to {path} this run")
            mode = "a" if sheets_done else "w"
            kwargs = {"if_sheet_exists": "error"} if mode == "a" else {}
            with pd.ExcelWriter(path, engine="openpyxl", mode=mode, **kwargs) as writer:
                df.to_excel(writer, sheet_name=sheet, index=False)
            sheets_done.add(sheet)
            print(f"wrote {len(df)} rows -> {path}#{sheet}")
    else:
        raise SystemExit(f"export: unsupported file extension '{suffix}' (use .csv or .xlsx) -- {path}")


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
    # tracks which (resolved path, sheet name) pairs PRAGMA export --sheet
    # has already written this run, across the mother script and any
    # included children -- see write_result.
    xlsx_sheets = {}

    top_level_path = script_path.resolve()
    show_result = True
    result_df = None
    last_cursor = None
    for stmt, source_path in statements:
        if not directive_text(stmt):
            # nothing left once comment/blank lines are stripped -- the
            # whole statement was commented out. Skip it rather than
            # sending it to sqlite: a no-op execute() still clears
            # result_df/last_cursor, which would otherwise make
            # commenting out the last real line of a script look like
            # an action query with nothing to show.
            continue
        if UDF_EXTRA_PRAGMA_RE.match(directive_text(stmt)):
            continue
        export_match = EXPORT_PRAGMA_RE.match(directive_text(stmt))
        if export_match:
            if result_df is None:
                raise SystemExit(f"PRAGMA export: no result set to export -- {stmt}")
            export_args = build_export_pragma_parser().parse_args(shlex.split(export_match.group(1)))
            write_result(result_df, export_args.path, sheet=export_args.sheet, xlsx_sheets=xlsx_sheets)
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
        show_result_match = SHOW_RESULT_PRAGMA_RE.match(directive_text(stmt))
        if show_result_match:
            value = show_result_match.group(1).strip().lower()
            if value not in ("on", "off"):
                raise SystemExit(f"PRAGMA show_result: expected 'on' or 'off' -- {stmt}")
            # top-level only -- an include's setting is ignored (see docstring).
            if source_path == top_level_path:
                show_result = value == "on"
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
    elif not show_result:
        pass
    elif result_df is not None:
        # SQL NULL becomes NaN/None once fetchall()'s rows go into a
        # DataFrame (pandas upcasts an int/float column with a missing
        # value to float64+NaN) -- fillna('') displays it as blank,
        # same as NULL means nothing, not the literal text "NaN".
        print(result_df.fillna("").to_string(index=False))
    elif last_cursor is None:
        # every statement in the script was commented out (or it had
        # none) -- nothing ever ran.
        print("no result set (nothing executed)")
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

"""UDFs (user-defined SQL functions) for run_sql.py.

run_sql.py calls register_udfs() on every run with udf_definitions.csv
(next to this file), so everything listed there is usable in any script.
A single script can add more with   PRAGMA udf_extra = 'my_udfs.csv';

csv format (semicolon, utf-8-sig), one row per SQL function:

    sql_name;module;python_name;num_args;deterministic;path

  sql_name       name to call from SQL
  module         python module holding the function (import name, no .py)
  python_name    function inside that module
  num_args       argument count sqlite is told about (-1 = any number)
  deterministic  1 if same input always gives same output (lets sqlite optimise)
  path           optional extra directory to import `module` from (~ allowed).
                 The csv's own directory is always importable.

A function returning a dict or list is stored as JSON text (sqlite has no
dict type) -- pull fields out in SQL with json_extract(col, '$.field').
"""
import csv
import importlib
import json
import sys
from pathlib import Path

DEFAULT_UDF_CSV = Path(__file__).resolve().parent / "udf_definitions.csv"


def my_upper(s):
    """Example UDF: upper-case a string; NULL in, NULL out."""
    return None if s is None else s.upper()


def _json_if_container(fn):
    def wrapper(*args):
        result = fn(*args)
        if isinstance(result, (dict, list)):
            return json.dumps(result, default=str)
        return result
    wrapper.__name__ = getattr(fn, "__name__", "udf")
    return wrapper


def _add_to_sys_path(directory):
    directory = str(directory)
    if directory not in sys.path:
        sys.path.append(directory)


def register_udfs(conn, csv_path):
    """Register every function listed in csv_path on conn."""
    csv_path = Path(csv_path).expanduser()
    if not csv_path.exists():
        raise SystemExit(f"udf definitions not found: {csv_path}")
    _add_to_sys_path(csv_path.resolve().parent)

    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            if not row.get("sql_name"):
                continue
            if row.get("path"):
                _add_to_sys_path(Path(row["path"]).expanduser())
            where = f"{csv_path.name}: {row['sql_name']}"
            try:
                module = importlib.import_module(row["module"])
            except ImportError as e:
                raise SystemExit(f"{where}: cannot import module '{row['module']}' ({e})")
            fn = getattr(module, row["python_name"], None)
            if fn is None:
                raise SystemExit(f"{where}: module '{row['module']}' has no function '{row['python_name']}'")
            conn.create_function(
                row["sql_name"],
                int(row["num_args"]),
                _json_if_container(fn),
                deterministic=row.get("deterministic", "1") == "1",
            )

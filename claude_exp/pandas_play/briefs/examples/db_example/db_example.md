# db_example

A small toolkit for using SQLite as a local working store instead of a "csv database":
load csv/xlsx into typed tables, run SQL scripts against them, and extend SQL with Python
functions (UDFs). Everything is plain Python 3 + pandas -- no installs beyond that.

Run everything from this directory with `python3`.

## Layout

```
db_example/
  config_loader.py        reads db_storage_dir from a config.json
  load_table.py           csv/xlsx -> SQLite table
  run_sql.py              run a .sql script, display / export the last result set
  run_sql_udf.py          UDF loader + built-in UDFs (my_upper)
  udf_definitions.csv     the always-registered UDFs
  create_sp.py            older demo: registering a function by hand (see "UDFs" below)
  field_definitions.csv   column typing for load_table.py
  load.sh / load_test.sh  load prod/test fixtures
  build_test_input.py     builds test/input from prod/input
  test_run_sql_udf.py     unit + end-to-end tests for the UDF feature
  prod/  test/            each has its own config.json and input/ directory
  samples/                small self-contained examples (own config.json)
```

## Environments and config

`--env prod|test` selects `<env>/config.json`; `--config PATH` overrides that with any
config.json (e.g. `samples/config.json`). The one field that matters is `db_storage_dir`:
where the `.db` files live. It is deliberately a local temp directory, **not** a synced
OneDrive folder -- a live SQLite file must not be synced. `{TEMP}` in the value is replaced
by the `TEMP` environment variable. `samples/sync.sh` copies the closed `.db` files into
`onedrive_sync_dir` as one-way at-rest snapshots.

## Loading data -- `load_table.py`

```
python3 load_table.py <infile> <db> <table> [--sheet NAME] (--env prod|test | --config PATH)
```

- `infile`: `.csv` (`;` separated, utf-8-sig, header row) or `.xlsx`.
- The table is dropped and recreated on every load.
- **Every column is TEXT by default** -- no inference, so no NaN trap. Only columns listed in
  `field_definitions.csv` (`table;field;type;sql_column_name`) are converted. Types use
  pandas names: `int`/`integer`, `float`, `date`, `datetime`/`timestamp`.
- `sql_column_name` (optional) stores the column under another name.
- CSVs are read in chunks and committed once at the end.

`load.sh --env prod|test` loads `a_cust`, `c_cust`, `d_cust` into the `download` db.
`load_test.sh` first builds a referentially consistent subset of prod into `test/input`
(`num_test_entries` from `prod/config.json`, plus the keys in `usual_suspects.csv`, plus
orphan rows) and then loads it with `load.sh --env test`.

## Running SQL -- `run_sql.py`

```
python3 run_sql.py <script.sql> [--db download] [--output out.csv] (--env prod|test | --config PATH)
```

- Runs every `;`-separated statement; comments are SQLite's own `--`.
- A script ending in a SELECT prints the result; `--output` writes it to `.csv`
  (`;` separator, utf-8-sig) or `.xlsx`. A script ending in an action query reports the
  rows affected.
- **Script directives** are written as `PRAGMA name = 'value';`. run_sql.py intercepts them;
  a plain `sqlite3` client silently ignores unknown pragmas, so every script stays valid SQL.

| Directive | Effect |
|---|---|
| `PRAGMA export = 'file.csv';` | write the latest result set to `.csv`/`.xlsx` at that point in the script |
| `PRAGMA udf_extra = 'x.csv';` | register the UDFs listed in `x.csv` for this script only |

Directives may be preceded by `--` comment lines.

## UDFs -- your own SQL functions

SQLite has no `CREATE FUNCTION`/stored procedures. The nearest thing is a Python function
registered on the *connection* with `conn.create_function(...)`. That registration is not
saved in the `.db` file, so it must be redone on every run -- which is what `run_sql.py`
now does automatically. (`create_sp.py` is the original hand-written demonstration of this,
including registering one name at several argument counts.)

### Always-on UDFs: `udf_definitions.csv`

```
sql_name;module;python_name;num_args;deterministic;path
my_upper;run_sql_udf;my_upper;1;1;
```

| Column | Meaning |
|---|---|
| `sql_name` | the name you call in SQL |
| `module` | Python module holding the function (import name, no `.py`) |
| `python_name` | function inside that module |
| `num_args` | argument count told to SQLite (`-1` = any) |
| `deterministic` | `1` if the same input always gives the same output |
| `path` | optional extra directory to import `module` from; `~` allowed |

Add a UDF by writing the function and adding a row. Example: `SELECT my_upper(name) FROM a_cust;`

### Per-script UDFs: `PRAGMA udf_extra`

```sql
PRAGMA udf_extra = 'udf_extra.csv';   -- same csv format; path relative to THIS .sql script
SELECT validate_COMPANY_ID('12345674', 'DK');
```

The pragma is pre-scanned before any statement runs, so its position in the script doesn't matter.

### Functions that return dicts or lists

SQLite values are scalars only (text, number, NULL, blob). If a UDF returns a `dict` or
`list`, the loader stores it as **JSON text**. Read fields with SQLite's JSON functions:

```sql
SELECT json_extract(validate_COMPANY_ID(id, 'DK'), '$.validation_result') AS is_valid
FROM   customers;
```

NULL in should give NULL out -- guard for `None` in the function.

### Using code from another directory tree (the `path` trick)

Goal: call `company_identifiers.validate_COMPANY_ID` from `~/containers/snippets/`, a class
that lives outside this project, without copying it or installing it.

Three pieces work together (`samples/`):

```
udf_extra.csv:
sql_name;module;python_name;num_args;deterministic;path
validate_COMPANY_ID;udf_company;validate_company_id;2;1;~/containers/snippets
```

```python
# udf_company.py -- lives next to udf_extra.csv
from company_identifiers import company_identifiers     # resolved via the path column
_ci = company_identifiers()                              # built once, reused per row

def validate_company_id(s, country_code):
    if s is None or country_code is None:
        return None
    return _ci.validate_COMPANY_ID(s, country_code)      # dict -> JSON text by the loader
```

How it resolves, in the order `register_udfs()` does it:

1. The **csv's own directory** is put on `sys.path`, so `udf_company` (the small wrapper)
   is importable with no `path` value at all.
2. For each row, its **`path` value** (`~` expanded) is put on `sys.path` *before* the
   module is imported. `import udf_company` then runs, and *its* `import company_identifiers`
   succeeds because `~/containers/snippets` is now on the path. That's the trick: the `path`
   column doesn't have to name the wrapper's directory -- it makes the directory of
   whatever the wrapper imports visible.
3. `getattr(module, python_name)` fetches the function and `create_function` registers it.

Why a wrapper instead of pointing the csv straight at the class:

- `create_function` needs a plain function; `validate_COMPANY_ID` is an *instance method*,
  so an instance has to exist. The wrapper creates it once at import time rather than per row.
- The class returns a dict; the wrapper is where you shape the result (return the dict, a
  bool, or one field).

Gotchas:

- `sys.path` is **process-wide**: directories are *appended*, so anything already earlier
  on the path wins. Two directories containing the same module name will clash -- give
  wrapper modules distinctive names (`udf_company`, not `company`).
- The import runs at **registration time**, so a wrong path, module, or function name fails
  immediately with a message naming the csv and the SQL function, before any SQL runs.
- `PRAGMA udf_extra` paths are relative to the `.sql` script; `path` column values are used
  as written (absolute or `~`), not relative to anything.
- If the imported file itself imports its own siblings, they resolve too, because its
  directory is on `sys.path`.

## Examples

```
python3 run_sql.py samples/udf_example.sql --db udf_demo --config samples/config.json
```

prints `my_upper`, the raw JSON result of `validate_COMPANY_ID`, and its `validation_result`
extracted with `json_extract`.

## Tests

```
python3 -m unittest test_run_sql_udf -v
```

Covers CSV registration, `num_args`, the `path` column, dict-to-JSON, error messages, the
`company_identifiers` example (skipped if `~/containers/snippets` is missing), and
`run_sql.py` end to end including `PRAGMA udf_extra` position and comment handling.

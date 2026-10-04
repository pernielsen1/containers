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
  anacredit_postal_code.py  AnaCredit_PostalCode class (postal code format per country) + UDF wrappers
  postal_code_formats.csv country;rule;pattern -- 158 regexes from the Bundesbank handbook v22 s4.5
  create_sp.py            older demo: registering a function by hand (see "UDFs" below)
  field_definitions.csv   column typing for load_table.py
  load.sh / load_test.sh  load prod/test fixtures
  build_test_input.py     builds test/input from prod/input
  test_run_sql_udf.py     unit + end-to-end tests for the UDF feature
  test_anacredit_postal_code.py  tests for the postal code class and its UDFs
  test_run_sql_include.py tests for PRAGMA include
  test_run_sql_load_table.py  tests for PRAGMA load_table
  test_run_sql_print.py   tests for PRAGMA print
  test_run_sql_show_result.py  tests for PRAGMA show_result
  test_run_sql_script_var.py  tests for PRAGMA script_var
  test_run_sql_comment_only.py tests for skipping fully-commented-out statements
  test_run_sql_export_sheets.py  tests for PRAGMA export --sheet
  test_run_sql_split.py   tests for the statement splitter (';' in comments/strings)
  test_load_table.py      CLI tests for --encoding/--delimiter/--decimal
  test_table_loader.py    tests for the TableLoader class (caching, aliases, ...)
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
python3 load_table.py <infile> <db> <table> [--sheet NAME]
        [--encoding ENC] [--delimiter CHAR] [--decimal CHAR] (--env prod|test | --config PATH)
```

- `infile`: `.csv` (header row) or `.xlsx`.
- CSV format options (rejected for `.xlsx`):

| Option | Default | Notes |
|---|---|---|
| `--encoding` | `utf-8-sig` | reads plain utf-8 identically and strips the BOM Excel adds; use e.g. `latin-1` for old exports. A wrong encoding is an error, never garbled text |
| `--delimiter` | `;` | one character, `\t`, or a name from `DELIMITER_ALIASES` (`comma`, `semicolon`/`semi_colon`, `tab`, `pipe`, `space`) -- case-insensitive |
| `--decimal` | `,` | applies to `float` columns only. A `.` in the data is still accepted with the default; pass `--decimal .` to make `1,5` an error |

- The table is dropped and recreated on every load.
- **Every column is TEXT by default** -- no inference, so no NaN trap. Only columns listed in
  `field_definitions.csv` (`table;field;type;sql_column_name`) are converted. Types use
  pandas names: `int`/`integer`, `float`, `date`, `datetime`/`timestamp`, or `str` (an
  explicit no-op -- see defaults below). That file is always `load_table.py`'s own (next to
  it in this directory) -- not resolved relative to whatever script or `PRAGMA load_table`
  triggered the load.
- `sql_column_name` (optional) stores the column under another name.
- **A row with a blank `table`** (e.g. `;my_key;int;`) sets a *default* type/rename for any
  field with that name, across every table -- but only where the field actually shows up; a
  table whose csv has no `my_key` column is simply unaffected. A row naming a table
  explicitly (e.g. `table_with_str_my_key;my_key;str;`) wins outright for that field on that
  table, replacing the default's type *and* rename together (not merged column by column) --
  `str` is exactly for this, an explicit "stay plain text" that opts one table back out of an
  inherited default. Runnable version: `samples/default_field_and_print_example.sql`, using
  the `;my_key;int;` row already in this directory's `field_definitions.csv`.
- CSVs are read in chunks and committed once at the end.
- The load itself is `TableLoader.load(conn, infile, table, ...)` -- a class working against
  an already-open connection. `main()` is a thin CLI wrapper around it (resolve config, open
  a connection, call `.load()`). `run_sql.py`'s `PRAGMA load_table` (below) is the other
  caller: it builds **one `TableLoader` for the whole script run** and reuses it across every
  `PRAGMA load_table` in that script, so `field_definitions.csv` is read once and cached
  instead of re-read on every load.

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
  rows affected. `PRAGMA show_result = 'off';` (below) silences both.
- A statement that's entirely a `--` comment (nothing left once comment/blank lines are
  stripped) is skipped rather than run -- so commenting out the last real line of a script
  doesn't erase the result that would otherwise have been shown/exported. This applies
  anywhere in the script, not just the last statement.
- **Script directives** are written as `PRAGMA name = 'value';`. run_sql.py intercepts them;
  a plain `sqlite3` client silently ignores unknown pragmas, so every script stays valid SQL.

| Directive | Effect |
|---|---|
| `PRAGMA export = 'file.csv';` | write the latest result set to `.csv`/`.xlsx` at that point in the script |
| `PRAGMA export = 'file.xlsx --sheet Name';` | same, but add `Name` as a sheet in that workbook instead of overwriting the file |
| `PRAGMA udf_extra = 'x.csv';` | register the UDFs listed in `x.csv` for this script only |
| `PRAGMA include = 'other.sql';` | splice that script's statements in at this point |
| `PRAGMA load_table = 'infile table ...';` | load a csv/xlsx into a table, right here |
| `PRAGMA print = 'message';` | print `message` to the console, right here |
| `PRAGMA show_result = 'off';` | don't show the last result set at the end (top-level script only) |
| `PRAGMA script_var = 'name=value';` / `'name=$ENVVAR';` | define a variable; later use `${name}` in PRAGMA directives only (`export` path, `print`, `load_table`...) -- never expanded in plain SQL. `$ENVVAR` takes the environment variable's value, e.g. `'out=$HOME'` then `PRAGMA export = '${out}/res.csv';`. A value may itself use earlier variables: `'outfile=${out}/res.csv'` |

Directives may be preceded by `--` comment lines. A script is split into statements on `;`,
but only a `;` outside a `--` comment, a `/* */` comment, a `'string'` and a `"quoted name"`
ends a statement, so comments and quoted text may contain `;` freely.

### Reusing a script: `PRAGMA include`

```sql
-- formatting.sql: shared setup, no PRAGMA export of its own
CREATE VIEW IF NOT EXISTS my_view AS
SELECT key, my_upper(desc) AS desc_upper, a_number
FROM table_1;
```

```sql
-- mother.sql: reuses the view above, decides its own filter and export
PRAGMA include = 'formatting.sql';

SELECT * FROM my_view WHERE a_number > 15;
PRAGMA export = 'out.csv';
```

Runnable version: `samples/include_formatting.sql` + `samples/include_mother.sql` (see
**Examples** below).

- Included statements are spliced in **in place**, in order -- statements after the include
  in the mother script see whatever the included script created (tables, views), and a
  `PRAGMA export`/`udf_extra`/another `include` inside the included script still runs
  exactly where it's written.
- **Recursive**: an included script can itself include another. Two scripts including the
  same shared script (a "diamond") is fine; a script including itself, directly or through
  a chain, is rejected with an error naming the cycle instead of hanging.
- **Path resolution -- relative to the file that contains the directive**, not the
  top-level script you passed on the command line. This applies to `udf_extra` too (not
  just `include`): if `formatting.sql` has its own `PRAGMA udf_extra = 'x.csv';`, `x.csv`
  is looked up next to `formatting.sql`, regardless of which mother script included it or
  how deep the include chain is. That's what makes a shared script relocatable -- move
  `formatting.sql` (and its `x.csv`) anywhere and its own relative paths still resolve,
  without touching whichever mother script includes it. (`PRAGMA export` paths are
  unaffected by any of this -- they're resolved the way they always were, against the
  current working directory.)
- A missing include file, or a cycle, is reported before any SQL statement runs.

### Loading a table mid-script: `PRAGMA load_table`

```sql
PRAGMA load_table = 'table_1.csv table_1';

SELECT * FROM table_1;
```

The quoted value is `load_table.py`'s own CLI arguments, minus the ones that pick a
database -- `--db`/`--env`/`--config` don't apply, the connection is already open -- so the
same flags work the same way:

```sql
PRAGMA load_table = 'big.csv entries --delimiter comma --decimal .';
PRAGMA load_table = '"prod/input/a file.xlsx" a_cust --sheet Sheet2';
```

Runnable version: `samples/load_table_pragma_example.sql`.

- The value is split the way a shell would (quoting for a path with spaces works, as in the
  second example above), then parsed with the same flag names as the command line.
- `infile` is resolved relative to the file the `PRAGMA` is written in -- the same rule as
  `include`/`udf_extra`. `field_definitions.csv`, by contrast, is always `load_table.py`'s own
  and unaffected by where the `PRAGMA` lives (see **Loading data** above).
- Runs **in place**, like `export` -- not pre-scanned like `include`/`udf_extra` -- so a later
  statement in the script can query the table it just loaded. It isn't itself a query, so it
  doesn't touch the "last result set" that `--output`/`PRAGMA export` would write.
- A missing `infile` or a missing required argument (`table`) is reported before any further
  SQL runs, the same way a missing `include` file is.
- The `--delimiter comma`/`semi_colon`/`tab`/`pipe`/`space` aliases exist mainly for this
  PRAGMA: the names are easier to read than a bare `;` in a PRAGMA value (a `;` inside the quoted
  value no longer splits the statement). See `DELIMITER_ALIASES` in `load_table.py`.

### A console message: `PRAGMA print`

```sql
PRAGMA load_table = 'export_input.csv staging';
PRAGMA print = 'staging loaded -- now open it in Excel and confirm the totals, then re-run';
SELECT * FROM staging;
```

Prints the message right then, in place -- useful for a script that has a manual step in the
middle of it (open a file, sanity-check something) and wants to say so on the console at that
point rather than leaving it to a README. Like `load_table`, it isn't a query and doesn't
touch the last result set.

### One workbook, several sheets: `PRAGMA export ... --sheet`

```sql
SELECT * FROM daily_totals;
PRAGMA export = 'out/daily.xlsx --sheet Totals';

SELECT * FROM daily_detail;
PRAGMA export = 'out/daily.xlsx --sheet Detail';
```

`--sheet` is xlsx only (an error on `.csv`). A plain `PRAGMA export = 'file.xlsx';` (no
`--sheet`) still overwrites the whole file each time, exactly as before -- multi-sheet
behaviour only kicks in once a script names a sheet. Naming one instead appends that sheet to
the workbook already being built at that path, so several `PRAGMA export --sheet` calls in one
run -- including one written inside an included child script -- end up as sheets of one
workbook rather than each overwriting the last. The same path+sheet name twice in one run is
an error (a mistake to notice, not something to silently drop a sheet over).

### Silent in production: `PRAGMA show_result`

```sql
PRAGMA show_result = 'off';
PRAGMA load_table = 'daily.csv staging';
SELECT * FROM staging;
PRAGMA export = 'out/daily.csv';
```

By default the last result set is shown on the console when the script ends -- handy
interactively, noise in a production stream. `'off'` suppresses that (and the
`no result set (action query)` line); `'on'` is the default. Anywhere in the script -- it's
only acted on at the end. `PRAGMA print` messages, `PRAGMA export`'s `wrote N rows` line and
`--output` are all unaffected. Honoured **only in the top-level script**: inside an included
file it's ignored, so a shared include can't silently turn output off for every script using
it (and a script run standalone with `'off'` can still be included elsewhere). Any value
other than `on`/`off` is an error.

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

**AnaCredit postal codes** (`anacredit_postal_code.py`, rules in `postal_code_formats.csv`):

| UDF | Returns |
|---|---|
| `anacredit_postal_valid(postal_code, country)` | 1 if the code fully matches the country's regex (or the country has no rule), else 0; NULL in -> NULL |
| `anacredit_postal_verbosed(postal_code, country)` | the code with noise removed and the separator restored (`'12345','SE'` -> `'123 45'`, `'12345','PL'` -> `'12-345'`, `'123 45','DE'` -> `'12345'`); NULL if it cannot be made valid |

Example: `SELECT * FROM a_cp WHERE anacredit_postal_valid(postal_code, country) = 0;`
`verbosed` tries the bare letters+digits, then one blank or `-` at each position -- one separator is
enough for every handbook format. The CSV follows the handbook verbatim, which differs from
`AnaCredit/codelists/postal_code_formats.json` for JE (blank required), KZ and MT (extra alternatives);
CZ is the handbook regex made Python-valid (`(\s)?{1}` is a regex error).

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

```
python3 load_table.py samples/table_1.csv include_demo table_1 --config samples/config.json
python3 run_sql.py samples/include_mother.sql --db include_demo --config samples/config.json
```

loads `table_1`, then runs `include_mother.sql`, which pulls in `include_formatting.sql`'s
view and exports its own filtered result to `samples/include_mother_out.csv`.

```
python3 run_sql.py samples/load_table_pragma_example.sql --db load_table_demo --config samples/config.json
```

loads `table_1` via `PRAGMA load_table` (no separate `load_table.py` call needed) and prints it.

```
python3 run_sql.py samples/default_field_and_print_example.sql --db defaults_demo --config samples/config.json
```

loads `my_key_example.csv`, with `my_key` typed as `int` purely from the default row already
in `field_definitions.csv` (no row for this table at all), then prints a `PRAGMA print`
message before showing the result.

## Tests

```
python3 -m unittest test_run_sql_udf test_run_sql_include test_run_sql_load_table test_run_sql_print test_run_sql_show_result test_run_sql_comment_only test_run_sql_export_sheets test_load_table test_table_loader -v
```

`test_run_sql_udf.py` covers CSV registration, `num_args`, the `path` column, dict-to-JSON,
error messages, the `company_identifiers` example (skipped if `~/containers/snippets` is
missing), and `run_sql.py` end to end including `PRAGMA udf_extra` position and comment
handling. `test_run_sql_include.py` covers splicing, statement ordering, nested/relative
path resolution, cycle detection, and export/udf_extra inside an included script.
`test_run_sql_load_table.py` covers `PRAGMA load_table` end to end, including the
`semi_colon` alias and use from inside an included script. `test_run_sql_print.py` covers
message ordering, comment handling, and that it doesn't disturb the last result set.
`test_run_sql_show_result.py` covers suppression of the result/action-query line, position
independence, print/export/`--output` still working, on/off case-insensitivity, rejecting
other values, and being ignored inside an include. `test_run_sql_comment_only.py` covers a
fully-commented-out statement being skipped rather than clearing the result set, both as the
last statement and mid-script, and the case where every statement is commented out.
`test_run_sql_export_sheets.py` covers `PRAGMA export ... --sheet`: plain export still
overwriting the whole file, two sheet names building one workbook (including one written from
an included child script), the same path+sheet twice being an error, and `--sheet` being
rejected on `.csv`.
`test_load_table.py` covers the CLI's `--encoding`/`--delimiter`/`--decimal`.
`test_table_loader.py` covers the `TableLoader` class directly: row counts, reload-drops-first,
the `field_definitions.csv` cache actually being read only once across multiple `.load()`
calls, the delimiter aliases, and the default-row precedence rules (a default applying, a
table-specific row overriding it outright, a default field absent from one table's csv being
silently ignored while a table's *own* row naming a missing column still errors).

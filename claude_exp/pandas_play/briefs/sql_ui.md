# sql_ui — local web client for run_sql.py

## Goal
Edit, save and run SQL scripts from a browser instead of VS Code + command prompt.
Results are NOT shown as a grid: scripts write them with `PRAGMA export`.
No new packages: Python stdlib only (plus what run_sql.py already needs).

## Files (in briefs/examples/db_example/)
- `sql_ui.py`   — stdlib `http.server` backend
- `sql_ui.html` — single static page, vanilla JS, no CDN
- `test_sql_ui.py` — tests (written before the code)
- `run_sql.py` is NOT modified.

## Usage
    python3 sql_ui.py [--port 8765] [--scripts-dir PATH] [--env prod|test] [--db NAME]
                      [--timeout 600] [--config PATH]
`--config` is passed through to run_sql.py (which then overrides --env's config.json) — used by tests.
Binds to 127.0.0.1 only. Prints the URL on start. Ctrl+C stops it.

## Scripts folder
- `--scripts-dir` (default: the `sql/` subdirectory next to sql_ui.py/run_sql.py, created if missing).
  `*.sql` files in it and in its subfolders (any depth) are listed.
- A script name is a `/`-separated path relative to scripts-dir (`more_sql/x.sql`). Each segment must match
  `^[A-Za-z0-9_-][A-Za-z0-9_.-]*$` (no leading dot, no `..`, no backslash, no empty segment), the last
  must end in `.sql`; anything else is rejected (400). The resolved path must stay inside scripts-dir.
- Folders are never created by the UI: saving/running into a missing folder is 400. Empty folders are listed.
- Includes / load_table / exports resolve relative to the script file, as on the CLI,
  because scripts are real files in that folder.

## Page
- Left: folders and scripts as an indented tree (click a script to open).
- Centre: tab bar of open scripts (one tab per script, `×` closes, `+` opens a new untitled
  tab), the `<textarea>` editor below it (monospace, Tab inserts spaces, no highlighting),
  then the status line and output pane. The focused tab is the one shown and acted on.
- Right: own column of vertical controls: `Save`, `Save as…` (prompt for name), `Run`, `Run & table`,
  `--env` dropdown (prod/test), `--db` text box. Save/Save as/Run act on the focused tab;
  env and db are global (shared by all tabs).
- `Run & table`: like `Run`, but the last result set is also shown as a grid (sticky header,
  first 1000 rows, note `N rows` / `first 1000 of N rows`) between the editor and the output
  pane. The grid is per tab; a plain `Run`, or a failed run, clears it. See "Run & table" below.
  A bar above the grid holds the row note and `Export CSV…` / `Export Excel…` (see "Exporting the table").
- Output pane — captured stdout + stderr, and a status line `exit 0 (1.2s)` / `exit 1 (...)`;
  kept per tab, so switching tabs shows that script's last result.
- Tabs: clicking a script in the tree opens it in a new tab, or focuses its tab if already open.
  Each tab keeps its own unsaved text across switches. Unsaved-change marker (`*`) in the tab
  label. Closing a tab with unsaved changes asks for confirmation. An untitled tab has no file
  yet: `Save` and `Run` are disabled until `Save as…` gives it a name. `Save as…` renames the
  tab to the new file (the old file stays on disk); it refuses a name already open in another tab.
- `Run` always saves first, so what runs is what is on screen. Only one run at a time
  (all tabs); text typed into the running tab during a run is kept and the tab stays dirty.

## Endpoints (JSON unless noted)
| Method | Path | Body | Result |
|---|---|---|---|
| GET  | `/`                | – | sql_ui.html |
| GET  | `/api/scripts`     | – | `{"scripts": ["a.sql", "sub/b.sql", ...], "dirs": ["sub", ...], "env": "prod", "db": "download"}` sorted by name |
| GET  | `/api/script?name=a.sql` | – | `{"name": "a.sql", "text": "..."}`; 404 if missing |
| POST | `/api/script`      | `{"name","text"}` | save (overwrite or create); `{"ok": true}` |
| POST | `/api/run_table`   | same as `/api/run` | saves, runs the script + temp export; as `/api/run` plus `"table": {"columns","rows","total","truncated"}` when exit 0 and a result set was exported |
| POST | `/api/export_xlsx` | `{"columns": [str], "rows": [[str]]}` | xlsx bytes (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`); non-string payload → 400 |
| POST | `/api/run`         | `{"name","text","env","db"}` | saves, then runs; `{"exit": 0, "output": "...", "seconds": 1.2}` |

## Run semantics
- Subprocess: `[sys.executable, "run_sql.py", <abs script path>, "--env", env, "--db", db]`,
  cwd = directory of run_sql.py, stderr merged into stdout, `shell=False`.
- `env` must be `prod` or `test`; `db` must match `^[A-Za-z0-9_.-]+$`. Otherwise 400.
- One run at a time: a second `/api/run` while one is active returns 409.
- Timeout (default 600 s, `--timeout`): process killed, `exit` = -1, output ends with `TIMEOUT`.
- Non-zero exit is a normal 200 response with `exit != 0` (the SystemExit message is in `output`).

## Safety
- 127.0.0.1 only; no auth (single local user). The SQL has full DB access — never bind elsewhere.
- Script names validated by regex above; resolved path must stay inside scripts-dir.
- `/api/run` never builds a shell string.
- Max request body 1 MB.

## Run & table
- Server writes the posted text to the real script (as `Run` does), then builds a hidden temp
  script (`.sql_ui_<uuid>.sql`, same folder as the real one so relative `PRAGMA include`
  resolves identically; the leading dot keeps it out of the listing) = script text, a `;` if
  the text doesn't end with one, and `PRAGMA export = '<tmpdir>/result.csv';`. It runs that with
  run_sql.py, parses the csv (`;` separated, utf-8-sig) and deletes temp script and dir in a
  `finally`. The saved script never contains the export line.
- A script with no result set (or any error) gives a normal non-zero exit, the message in the
  output pane and no table. A script's own `PRAGMA export` lines still run as written.
- Rows beyond `MAX_ROWS` (1000) are counted but not sent.

## Exporting the table
- Exports exactly the rows shown (so at most `MAX_ROWS`), not the full result.
- **CSV** is built in the browser in `run_sql.py`'s format: `;` separated, utf-8 with BOM, `"`
  quoting only for cells containing `;` `"` or a newline. Values are the strings from the
  exported csv, so decimals keep the comma.
- **Excel** is built by `/api/export_xlsx` (openpyxl, already required by run_sql.py). Cells
  that are plain numbers in csv notation (`-?(0|[1-9]\d*)(,\d+)?`, at most 15 digits) become
  numbers; anything else, e.g. `007` or a 20-digit id, stays text. Text is explicitly stored as
  text (never a formula -- a string starting with `=` written as a formula makes Excel say the
  file needs repair); control characters Excel can't store are dropped.
  The saved package's `docProps/core.xml` is post-processed: openpyxl 3.1.2 on Python 3.12 writes
  its dates as `...+00:00Z` (offset *and* Z), which is not a valid date, so Excel reports the file
  as needing repair even though the sheet itself is fine. They are rewritten to `...Z`.
- **Where it is saved:** `window.showSaveFilePicker` (Chrome/Edge) opens the native save dialog
  suggesting `<script name>.csv|.xlsx`; cancelling does nothing. Browsers without it (Firefox)
  fall back to a normal download into the browser's download folder.

## Out of scope (v1)
Syntax highlighting, result grid, restoring open tabs after a page reload, delete/rename, creating folders, auth, remote access.

## Tests (test_sql_ui.py, start server on an ephemeral port in a thread)
1. List returns only `*.sql` (including in subfolders, as `sub/c.sql`), sorted, plus `dirs`; ignores other files.
2. Load returns text; missing → 404.
3. Save creates and overwrites; file content on disk matches.
4. Bad names rejected (400): `../x.sql`, `sub/../../x.sql`, `/etc/x.sql`, `sub//x.sql`, dot-segments, backslashes, `x.txt`, empty, `.sql`.
4b. Subfolder script: save/load/run work; relative include resolves inside the subfolder; empty folder listed; saving into a missing folder → 400 and no folder created.
5. Run executes a script with `PRAGMA print`: exit 0, output contains the message.
6. Run on a script with a SQL error: exit != 0, error text in output, HTTP 200.
7. Run saves first: edited text (not disk text) is what runs.
8. Bad env / db → 400; missing env → 400; missing db → defaults to `download`.
9. Concurrent second run → 409.
10. Timeout kills the process and reports exit -1.
11. Relative `PRAGMA include` works from the scripts folder.
12. Server binds to 127.0.0.1 only.
13. Playwright smoke test: open page, pick script, edit, Run, output pane shows result,
    `*` marker (in the tab label) clears after Save.
15. Playwright: two scripts open as two tabs; re-clicking one focuses rather than duplicates;
    each tab keeps its unsaved text and its own output across switches (nothing written to disk).
16. Playwright: closing a tab (confirm when dirty — dismiss keeps, accept discards); untitled tab
    has Save and Run disabled.
17. `/api/run_table`: table columns/rows returned; works with and without trailing `;` / trailing comment; row cap and `truncated`; no result set or SQL error → non-zero exit, no `table`; real script saved without the export line, no temp files left, relative include works in a subfolder; bad env/name → 400.
18. Playwright: Run & table disabled until env chosen; grid shows header + cells; grid is per tab; plain Run clears it.
19. `/api/export_xlsx`: header + rows, numbers converted, `007` stays text; `=...` text, text with a comma, control chars and >15-digit numbers are safe (no `<f>` in the sheet xml); bad payload → 400; `core.xml` dates match `YYYY-MM-DDThh:mm:ssZ`.
20. Playwright: export via download fallback (csv content/BOM/quoting, xlsx content); via a stubbed
    `showSaveFilePicker` (suggested name, content written); picker cancel shows no alert.
14. Playwright: hold Run open across a poll/status tick — UI stays responsive, Run disabled while running.

## Decisions
- Scripts folder: `sql/` subdirectory next to run_sql.py.
- `--env` / `--db` behave exactly as in run_sql.py: `--db` defaults to `download`;
  `--env` has no default and must be chosen (CLI flag pre-selects the dropdown, otherwise
  Run is disabled until prod or test is picked). Nothing is read from config.json by the UI;
  run_sql.py does its own config lookup from `--env`.

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
- Centre: `<textarea>` editor (monospace, Tab inserts spaces, no highlighting).
- Toolbar: `Save`, `Save as…` (prompt for name), `Run`, `--env` dropdown (prod/test), `--db` text box.
- Bottom: output pane — captured stdout + stderr, and a status line `exit 0 (1.2s)` / `exit 1 (...)`.
- Unsaved-change marker (`*`) next to the script name.
- `Run` always saves first, so what runs is what is on screen.

## Endpoints (JSON unless noted)
| Method | Path | Body | Result |
|---|---|---|---|
| GET  | `/`                | – | sql_ui.html |
| GET  | `/api/scripts`     | – | `{"scripts": ["a.sql", "sub/b.sql", ...], "dirs": ["sub", ...], "env": "prod", "db": "download"}` sorted by name |
| GET  | `/api/script?name=a.sql` | – | `{"name": "a.sql", "text": "..."}`; 404 if missing |
| POST | `/api/script`      | `{"name","text"}` | save (overwrite or create); `{"ok": true}` |
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

## Out of scope (v1)
Syntax highlighting, result grid, tabs, delete/rename, creating folders, auth, remote access.

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
    `*` marker clears after Save.
14. Playwright: hold Run open across a poll/status tick — UI stays responsive, Run disabled while running.

## Decisions
- Scripts folder: `sql/` subdirectory next to run_sql.py.
- `--env` / `--db` behave exactly as in run_sql.py: `--db` defaults to `download`;
  `--env` has no default and must be chosen (CLI flag pre-selects the dropdown, otherwise
  Run is disabled until prod or test is picked). Nothing is read from config.json by the UI;
  run_sql.py does its own config lookup from `--env`.

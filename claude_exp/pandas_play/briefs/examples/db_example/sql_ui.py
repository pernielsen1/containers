#!/usr/bin/env python3
"""
sql_ui.py [--port 8765] [--scripts-dir PATH] [--env prod|test] [--db NAME]
          [--timeout 600] [--config PATH]

Local web client for run_sql.py (spec: briefs/sql_ui.md). Serves sql_ui.html
on 127.0.0.1 only; scripts are real *.sql files in --scripts-dir (default
the sql/ subdirectory next to this file). Run saves the script, then runs
run_sql.py on it as a subprocess and returns its combined output. Run & table does the
same on a hidden temp copy of the script with a PRAGMA export to a temp csv appended, and
returns that csv as a table (first MAX_ROWS rows).
--config is passed straight through to run_sql.py (overrides --env's
config.json) -- used by the tests.
"""
import argparse
import csv
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
SEG_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*$")   # one path segment, no leading dot
NAME_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*\.sql$")
DB_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
MAX_BODY = 1024 * 1024
MAX_ROWS = 1000
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
NUMBER_RE = re.compile(r"^-?(0|[1-9][0-9]*)(,[0-9]+)?$")   # run_sql.py csv: decimal comma, no leading zeros
DEFAULT_DB = "download"


class BadRequest(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def script_path(scripts_dir, name):
    """name is a '/'-separated path relative to scripts_dir, e.g. 'more/x.sql'."""
    bad = BadRequest(f"bad script name: {name!r}")
    if not isinstance(name, str):
        raise bad
    parts = name.split("/")
    if not all(SEG_RE.match(p) and p not in (".", "..") for p in parts) or not NAME_RE.match(parts[-1]):
        raise bad
    root = scripts_dir.resolve()
    path = (root / name).resolve()
    if root not in path.parents:
        raise bad
    return path


def list_scripts(scripts_dir):
    """(files, dirs): '/'-separated relative paths, sorted; dotted/odd names skipped."""
    root = scripts_dir.resolve()
    files, dirs = [], []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if not all(SEG_RE.match(part) for part in rel.parts):
            continue
        if p.is_dir() and not p.is_symlink():
            dirs.append(rel.as_posix())
        elif p.is_file() and NAME_RE.match(p.name):
            files.append(rel.as_posix())
    return files, dirs


def run_script(server, path, env, db):
    cmd = [sys.executable, str(HERE / "run_sql.py"), str(path), "--env", env, "--db", db]
    if server.config:
        cmd += ["--config", str(server.config)]
    start = time.time()
    proc = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    try:
        output, _ = proc.communicate(timeout=server.run_timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        output, _ = proc.communicate()
        output = (output or "") + "\nTIMEOUT"
        code = -1
    return {"exit": code, "output": output, "seconds": round(time.time() - start, 1)}


def read_table(csv_path):
    """The exported csv (run_sql.py format: ';' separated, utf-8-sig) as
    {columns, rows, total, truncated}, rows capped at MAX_ROWS."""
    rows, total = [], 0
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter=";")
        columns = next(reader, [])
        for row in reader:
            total += 1
            if total <= MAX_ROWS:
                rows.append(row)
    return {"columns": columns, "rows": rows, "total": total, "truncated": total > MAX_ROWS}


def xlsx_value(v):
    """(value, is_text) for one csv string. Plain numbers (csv notation, at most
    15 digits -- Excel's precision) become numbers, everything else is text."""
    if NUMBER_RE.match(v) and len(v.replace("-", "").replace(",", "")) <= 15:
        return (float(v.replace(",", ".")) if "," in v else int(v)), False
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    return ILLEGAL_CHARACTERS_RE.sub("", v), True


def build_xlsx(columns, rows):
    """xlsx bytes for a table of strings (as returned by read_table). Text is always
    stored as text: openpyxl would otherwise turn a string starting with '=' into a
    formula, and an invalid one makes Excel demand a repair."""
    from openpyxl import Workbook
    ok = (isinstance(columns, list) and isinstance(rows, list)
          and all(isinstance(c, str) for c in columns)
          and all(isinstance(r, list) and all(isinstance(v, str) for v in r) for r in rows))
    if not ok:
        raise BadRequest("columns and rows must be lists of strings")
    wb = Workbook()
    ws = wb.active
    for r, row in enumerate([columns] + rows, start=1):
        for c, raw in enumerate(row, start=1):
            value, is_text = (raw, True) if r == 1 else xlsx_value(raw)
            cell = ws.cell(row=r, column=c, value=value)
            if is_text:
                cell.data_type = "s"
    buf = io.BytesIO()
    wb.save(buf)
    return fix_core_dates(buf.getvalue())


def fix_core_dates(xlsx):
    """openpyxl 3.1.2 on Python 3.12 stamps docProps/core.xml with '...+00:00Z' (offset AND
    Z). That is not a valid date: Excel says the file needs repair. Rewrite as '...Z'."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(xlsx)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "docProps/core.xml":
                data = data.replace(b"+00:00Z", b"Z")
            dst.writestr(item, data)
    return out.getvalue()


def run_script_table(server, target, text, env, db):
    """Run text (the script as shown) plus a trailing PRAGMA export to a temp
    csv. The temp script sits next to the real one -- hidden by its leading
    dot, so it isn't listed -- so relative includes resolve as for Run."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="sql_ui_"))
    tmp_script = target.parent / f".sql_ui_{uuid.uuid4().hex}.sql"
    out_csv = tmp_dir / "result.csv"
    try:
        body = text.rstrip()
        if not body.endswith(";"):
            body += "\n;"
        tmp_script.write_text(f"{body}\nPRAGMA export = '{out_csv.as_posix()}';\n",
                              encoding="utf-8", newline="")
        result = run_script(server, tmp_script, env, db)
        if result["exit"] == 0 and out_csv.exists():
            result["table"] = read_table(out_csv)
        return result
    finally:
        tmp_script.unlink(missing_ok=True)
        shutil.rmtree(tmp_dir, ignore_errors=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            # drain (bounded) so the client gets the 413 instead of a broken pipe
            remaining = min(length, 16 * MAX_BODY)
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
            self.close_connection = True
            raise BadRequest("request body too large", 413)
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            raise BadRequest("invalid JSON")

    def dispatch(self, fn):
        try:
            fn()
        except BadRequest as e:
            self.send_json(e.status, {"error": str(e)})
        except Exception as e:  # keep the server alive, tell the client
            self.send_json(500, {"error": f"{type(e).__name__}: {e}"})

    def do_GET(self):
        self.dispatch(self.get)

    def do_POST(self):
        self.dispatch(self.post)

    def get(self):
        url = urlparse(self.path)
        srv = self.server
        if url.path == "/":
            data = (HERE / "sql_ui.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif url.path == "/api/scripts":
            files, dirs = list_scripts(srv.scripts_dir)
            self.send_json(200, {"scripts": files, "dirs": dirs,
                                 "env": srv.default_env, "db": srv.default_db})
        elif url.path == "/api/script":
            name = parse_qs(url.query).get("name", [""])[0]
            path = script_path(srv.scripts_dir, name)
            if not path.is_file():
                raise BadRequest(f"{name} not found", 404)
            self.send_json(200, {"name": name, "text": path.read_text(encoding="utf-8")})
        else:
            raise BadRequest("not found", 404)

    def post(self):
        srv = self.server
        path = urlparse(self.path).path
        if path == "/api/script":
            body = self.read_body()
            target = script_path(srv.scripts_dir, body.get("name"))
            if not target.parent.is_dir():
                raise BadRequest(f"folder does not exist: {body.get('name')!r}")
            target.write_text(str(body.get("text", "")), encoding="utf-8", newline="")
            self.send_json(200, {"ok": True})
        elif path == "/api/export_xlsx":
            body = self.read_body()
            data = build_xlsx(body.get("columns"), body.get("rows"))
            self.send_response(200)
            self.send_header("Content-Type", XLSX_TYPE)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path in ("/api/run", "/api/run_table"):
            body = self.read_body()
            target = script_path(srv.scripts_dir, body.get("name"))
            if not target.parent.is_dir():
                raise BadRequest(f"folder does not exist: {body.get('name')!r}")
            env = body.get("env")
            if env not in ("prod", "test"):
                raise BadRequest("env must be prod or test")
            db = body.get("db") or DEFAULT_DB
            if not isinstance(db, str) or not DB_RE.match(db):
                raise BadRequest(f"bad db name: {db!r}")
            if not srv.run_lock.acquire(blocking=False):
                raise BadRequest("a run is already in progress", 409)
            try:
                target.write_text(str(body.get("text", "")), encoding="utf-8", newline="")
                if path == "/api/run":
                    result = run_script(srv, target, env, db)
                else:
                    result = run_script_table(srv, target, str(body.get("text", "")), env, db)
                self.send_json(200, result)
            finally:
                srv.run_lock.release()
        else:
            raise BadRequest("not found", 404)


def create_server(scripts_dir, port=8765, env=None, db=DEFAULT_DB, timeout=600, config=None):
    scripts_dir = Path(scripts_dir)
    scripts_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.scripts_dir = scripts_dir
    server.default_env = env
    server.default_db = db
    server.run_timeout = timeout
    server.config = config
    server.run_lock = threading.Lock()
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--scripts-dir", default=str(HERE / "sql"))
    parser.add_argument("--env", choices=["prod", "test"])
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--config")
    args = parser.parse_args()
    server = create_server(args.scripts_dir, args.port, args.env, args.db, args.timeout, args.config)
    print(f"sql_ui: http://127.0.0.1:{server.server_address[1]}/  (scripts: {server.scripts_dir})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

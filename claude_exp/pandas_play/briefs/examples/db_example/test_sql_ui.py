"""Tests for sql_ui.py (see briefs/sql_ui.md).

Run:  python3 -m unittest test_sql_ui -v   (from db_example/)
"""
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import sql_ui


class UiCase(unittest.TestCase):
    timeout = 600

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.scripts = self.dir / "sql"
        self.scripts.mkdir()
        self.cfg = self.dir / "config.json"
        self.cfg.write_text(json.dumps({"db_storage_dir": str(self.dir / "db")}))
        self.server = sql_ui.create_server(self.scripts, port=0, config=self.cfg,
                                           timeout=self.timeout)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read() or b"null") if r.headers.get_content_type() == "application/json" else r.read()
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    def run_body(self, name="s.sql", text="PRAGMA print = 'hello';", **kw):
        body = {"name": name, "text": text, "env": "test", "db": "t"}
        body.update(kw)
        return body


class TestScripts(UiCase):
    def test_list_only_sql_sorted(self):
        (self.scripts / "b.sql").write_text("x")
        (self.scripts / "a.sql").write_text("x")
        (self.scripts / "notes.txt").write_text("x")
        (self.scripts / "sub").mkdir()
        (self.scripts / "sub" / "c.sql").write_text("x")
        status, data = self.call("GET", "/api/scripts")
        self.assertEqual(status, 200)
        self.assertEqual(data["scripts"], ["a.sql", "b.sql"])
        self.assertEqual(data["db"], "download")

    def test_load_and_missing(self):
        (self.scripts / "a.sql").write_text("select 1;", encoding="utf-8")
        status, data = self.call("GET", "/api/script?name=a.sql")
        self.assertEqual((status, data["text"]), (200, "select 1;"))
        status, _ = self.call("GET", "/api/script?name=nope.sql")
        self.assertEqual(status, 404)

    def test_save_creates_and_overwrites(self):
        self.assertEqual(self.call("POST", "/api/script", {"name": "n.sql", "text": "one"})[0], 200)
        self.assertEqual((self.scripts / "n.sql").read_text(encoding="utf-8"), "one")
        self.call("POST", "/api/script", {"name": "n.sql", "text": "two"})
        self.assertEqual((self.scripts / "n.sql").read_text(encoding="utf-8"), "two")

    def test_bad_names_rejected(self):
        for name in ["../x.sql", "a/b.sql", "x.txt", "", ".sql", "..\\x.sql"]:
            with self.subTest(name=name):
                self.assertEqual(self.call("POST", "/api/script", {"name": name, "text": "x"})[0], 400)
                self.assertEqual(self.call("GET", "/api/script?name=" + urllib.parse.quote(name))[0], 400)
        self.assertEqual(list(self.dir.glob("x.*")), [])

    def test_body_too_large(self):
        status, _ = self.call("POST", "/api/script", {"name": "big.sql", "text": "x" * (1024 * 1024 + 1)})
        self.assertEqual(status, 413)

    def test_binds_localhost_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")


class TestRun(UiCase):
    def test_run_print(self):
        status, data = self.call("POST", "/api/run", self.run_body())
        self.assertEqual(status, 200)
        self.assertEqual(data["exit"], 0)
        self.assertIn("hello", data["output"])
        self.assertIn("seconds", data)

    def test_run_sql_error_is_200_nonzero(self):
        status, data = self.call("POST", "/api/run", self.run_body(text="SELEKT 1;"))
        self.assertEqual(status, 200)
        self.assertNotEqual(data["exit"], 0)
        self.assertIn("SELEKT", data["output"])

    def test_run_saves_posted_text_first(self):
        (self.scripts / "s.sql").write_text("PRAGMA print = 'old';")
        _, data = self.call("POST", "/api/run", self.run_body(text="PRAGMA print = 'new';"))
        self.assertIn("new", data["output"])
        self.assertNotIn("old", data["output"])
        self.assertIn("new", (self.scripts / "s.sql").read_text())

    def test_bad_env_db(self):
        self.assertEqual(self.call("POST", "/api/run", self.run_body(env="dev"))[0], 400)
        self.assertEqual(self.call("POST", "/api/run", self.run_body(env=""))[0], 400)
        body = self.run_body()
        del body["env"]
        self.assertEqual(self.call("POST", "/api/run", body)[0], 400)
        self.assertEqual(self.call("POST", "/api/run", self.run_body(db="a;b"))[0], 400)
        self.assertEqual(self.call("POST", "/api/run", self.run_body(db="../x"))[0], 400)

    def test_missing_db_defaults_to_download(self):
        body = self.run_body(text="CREATE TABLE t(a); INSERT INTO t VALUES (1);")
        del body["db"]
        status, data = self.call("POST", "/api/run", body)
        self.assertEqual((status, data["exit"]), (200, 0))
        self.assertTrue((self.dir / "db" / "download.db").exists())

    def test_relative_include(self):
        (self.scripts / "shared.sql").write_text("PRAGMA print = 'from shared';")
        _, data = self.call("POST", "/api/run",
                            self.run_body(text="PRAGMA include = 'shared.sql';"))
        self.assertEqual(data["exit"], 0)
        self.assertIn("from shared", data["output"])


class TestRunLimits(UiCase):
    timeout = 1

    def slow_script(self):
        # recursive CTE: a long-running query, no external sleep needed
        return ("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x < 500000000) "
                "SELECT count(*) FROM c;")

    def test_timeout_kills(self):
        t0 = time.time()
        status, data = self.call("POST", "/api/run", self.run_body(text=self.slow_script()))
        self.assertEqual(status, 200)
        self.assertEqual(data["exit"], -1)
        self.assertIn("TIMEOUT", data["output"])
        self.assertLess(time.time() - t0, 20)

    def test_concurrent_run_409(self):
        first = {}
        t = threading.Thread(target=lambda: first.update(
            r=self.call("POST", "/api/run", self.run_body(text=self.slow_script()))))
        t.start()
        time.sleep(0.4)
        status, _ = self.call("POST", "/api/run", self.run_body())
        self.assertEqual(status, 409)
        t.join()
        self.assertEqual(first["r"][1]["exit"], -1)


class TestBrowser(UiCase):
    timeout = 4

    def setUp(self):
        super().setUp()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("playwright not installed")
        self.pw = sync_playwright().start()
        try:
            self.browser = self.pw.chromium.launch()
        except Exception as e:
            self.pw.stop()
            self.skipTest(f"chromium not available: {e}")
        self.page = self.browser.new_page()
        (self.scripts / "a.sql").write_text("PRAGMA print = 'smoke';", encoding="utf-8")
        self.page.goto(f"http://127.0.0.1:{self.port}/")

    def tearDown(self):
        self.browser.close()
        self.pw.stop()
        super().tearDown()

    def test_smoke_edit_save_run(self):
        p = self.page
        p.click("text=a.sql")
        self.assertIn("smoke", p.input_value("#editor"))
        self.assertTrue(p.is_disabled("#run"))          # no env chosen yet
        p.select_option("#env", "test")
        p.fill("#db", "t")
        p.fill("#editor", "PRAGMA print = 'edited';")
        self.assertIn("*", p.inner_text("#title"))       # unsaved marker
        p.click("#save")
        p.wait_for_function("!document.querySelector('#title').innerText.includes('*')")
        self.assertIn("edited", (self.scripts / "a.sql").read_text())
        p.click("#run")
        p.wait_for_function("document.querySelector('#status').innerText.includes('exit 0')")
        self.assertIn("edited", p.inner_text("#output"))

    def test_run_held_open_across_ticks(self):
        p = self.page
        (self.scripts / "slow.sql").write_text(TestRunLimits.slow_script(None), encoding="utf-8")
        p.reload()
        p.click("text=slow.sql")
        p.select_option("#env", "test")
        p.fill("#db", "t")
        p.click("#run")
        p.wait_for_timeout(1500)                        # several ticks while running
        self.assertTrue(p.is_disabled("#run"))
        p.fill("#editor", p.input_value("#editor") + " ")   # UI still responsive
        p.wait_for_function("!document.querySelector('#run').disabled")


if __name__ == "__main__":
    unittest.main()

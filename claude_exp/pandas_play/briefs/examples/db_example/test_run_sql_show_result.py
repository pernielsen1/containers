"""Tests for PRAGMA show_result in run_sql.py: 'off' suppresses the
end-of-run display of the last result set (noise in a production
stream). Only honoured in the top-level script, not in an include.

Run:  python3 -m unittest test_run_sql_show_result -v   (from db_example/)
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class ShowResultCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        cfg = self.dir / "config.json"
        cfg.write_text(json.dumps({"db_storage_dir": str(self.dir / "db")}))
        self.cfg = cfg

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def run_script(self, sql_text, *extra_args):
        script = self.write("s.sql", sql_text)
        return subprocess.run(
            [sys.executable, str(HERE / "run_sql.py"), str(script), "--db", "t", "--config", str(self.cfg),
             *extra_args],
            capture_output=True, text=True, cwd=self.dir,
        )


class TestPragmaShowResult(ShowResultCase):
    def test_default_still_shows_last_result(self):
        r = self.run_script("SELECT 4242 AS x;")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("4242", r.stdout)

    def test_off_suppresses_last_result(self):
        r = self.run_script("PRAGMA show_result = 'off';\nSELECT 4242 AS x;")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("4242", r.stdout)
        self.assertEqual(r.stdout.strip(), "")

    def test_position_does_not_matter(self):
        r = self.run_script("SELECT 4242 AS x;\nPRAGMA show_result = 'off';")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("4242", r.stdout)

    def test_off_suppresses_action_query_message(self):
        r = self.run_script(
            "PRAGMA show_result = 'off';\nCREATE TABLE a (x INT);\nINSERT INTO a VALUES (1);"
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("no result set", r.stdout)

    def test_off_keeps_print_messages(self):
        r = self.run_script(
            "PRAGMA show_result = 'off';\nPRAGMA print = 'next: check totals';\nSELECT 4242 AS x;"
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("next: check totals", r.stdout)
        self.assertNotIn("4242", r.stdout)

    def test_off_keeps_export_and_its_message(self):
        out = self.dir / "e.csv"
        r = self.run_script(f"PRAGMA show_result = 'off';\nSELECT 4242 AS x;\nPRAGMA export = '{out}';")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("wrote 1 rows", r.stdout)
        self.assertIn("4242", out.read_text(encoding="utf-8-sig"))

    def test_off_still_writes_cli_output(self):
        out = self.dir / "o.csv"
        r = self.run_script("PRAGMA show_result = 'off';\nSELECT 4242 AS x;", "--output", str(out))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("4242", out.read_text(encoding="utf-8-sig"))

    def test_on_is_accepted_and_shows(self):
        r = self.run_script("PRAGMA show_result = 'on';\nSELECT 4242 AS x;")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("4242", r.stdout)

    def test_value_is_case_insensitive(self):
        r = self.run_script("PRAGMA SHOW_RESULT = 'OFF';\nSELECT 4242 AS x;")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("4242", r.stdout)

    def test_invalid_value_is_rejected(self):
        r = self.run_script("PRAGMA show_result = 'nope';\nSELECT 4242 AS x;")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("show_result", r.stderr)

    def test_preceded_by_comment_lines(self):
        r = self.run_script("-- production run\nPRAGMA show_result = 'off';\nSELECT 4242 AS x;")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("4242", r.stdout)

    def test_ignored_inside_an_included_script(self):
        self.write("included.sql", "PRAGMA show_result = 'off';")
        r = self.run_script("PRAGMA include = 'included.sql';\nSELECT 4242 AS x;")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("4242", r.stdout)


if __name__ == "__main__":
    unittest.main()

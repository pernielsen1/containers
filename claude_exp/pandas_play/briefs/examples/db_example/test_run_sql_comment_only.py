"""Tests for run_sql.py skipping a statement that's entirely a '--'
comment: it must not touch result_df/last_cursor, so commenting out
the last real line of a script doesn't turn the run into a "no result
set (action query)" with nothing shown/exported.

Run:  python3 -m unittest test_run_sql_comment_only -v   (from db_example/)
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class CommentOnlyCase(unittest.TestCase):
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


class TestCommentOnlyStatement(CommentOnlyCase):
    def test_commented_out_last_line_keeps_prior_result(self):
        r = self.run_script("SELECT 4242 AS x;\n-- PRAGMA export = 'out.csv';")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("4242", r.stdout)
        self.assertNotIn("no result set", r.stdout)

    def test_commented_out_last_select_keeps_prior_result(self):
        r = self.run_script("SELECT 4242 AS x;\n-- SELECT 1;")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("4242", r.stdout)

    def test_commented_out_statement_mid_script_is_skipped(self):
        r = self.run_script("-- disabled for now\n-- SELECT 1;\nSELECT 4242 AS x;")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("4242", r.stdout)

    def test_multiple_comment_lines_only_is_skipped(self):
        r = self.run_script("SELECT 4242 AS x;\n-- line one\n-- line two\n-- line three")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("4242", r.stdout)

    def test_all_statements_commented_out_reports_no_result_set(self):
        r = self.run_script("-- SELECT 1;\n-- SELECT 2;")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no result set", r.stdout)

    def test_commented_out_export_does_not_write_file(self):
        out = self.dir / "out.csv"
        r = self.run_script(f"SELECT 4242 AS x;\n-- PRAGMA export = '{out}';")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()

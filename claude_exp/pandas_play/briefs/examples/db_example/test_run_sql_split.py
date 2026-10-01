"""Tests for run_sql.split_statements: a ';' only ends a statement when it
is outside a '--' comment, a /* */ comment, a 'string' and a "quoted name".

Run:  python3 -m unittest test_run_sql_split -v   (from db_example/)
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_sql import split_statements  # noqa: E402


class TestSplitStatements(unittest.TestCase):
    def test_plain_split(self):
        self.assertEqual(split_statements("SELECT 1; SELECT 2;"), ["SELECT 1", "SELECT 2"])

    def test_no_trailing_semicolon(self):
        self.assertEqual(split_statements("SELECT 1; SELECT 2"), ["SELECT 1", "SELECT 2"])

    def test_semicolon_in_line_comment(self):
        sql = "-- a; b\nSELECT 1; -- x; y\nSELECT 2;"
        self.assertEqual(split_statements(sql), ["-- a; b\nSELECT 1", "-- x; y\nSELECT 2"])

    def test_semicolon_in_block_comment(self):
        self.assertEqual(split_statements("/* a; b\n c; */ SELECT 1; SELECT 2"),
                         ["/* a; b\n c; */ SELECT 1", "SELECT 2"])

    def test_semicolon_in_string(self):
        self.assertEqual(split_statements("SELECT 'a;b'; SELECT 2"), ["SELECT 'a;b'", "SELECT 2"])

    def test_escaped_quote_in_string(self):
        self.assertEqual(split_statements("SELECT 'it''s;ok'; SELECT 2"), ["SELECT 'it''s;ok'", "SELECT 2"])

    def test_semicolon_in_quoted_name(self):
        self.assertEqual(split_statements('SELECT 1 AS "a;b"; SELECT 2'), ['SELECT 1 AS "a;b"', "SELECT 2"])

    def test_comment_markers_inside_string_are_text(self):
        self.assertEqual(split_statements("SELECT '--'; SELECT '/*'; SELECT 3"),
                         ["SELECT '--'", "SELECT '/*'", "SELECT 3"])

    def test_apostrophe_in_comment_does_not_open_a_string(self):
        self.assertEqual(split_statements("-- don't\nSELECT 1; SELECT 2"), ["-- don't\nSELECT 1", "SELECT 2"])

    def test_pragma_with_semicolon_in_quoted_text(self):
        self.assertEqual(split_statements("PRAGMA print = 'a; b'; SELECT 1"),
                         ["PRAGMA print = 'a; b'", "SELECT 1"])

    def test_trailing_comment_kept_as_comment_only_statement(self):
        self.assertEqual(split_statements("SELECT 1; -- done"), ["SELECT 1", "-- done"])


class TestEndToEnd(unittest.TestCase):
    def test_script_with_semicolons_in_comments_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cfg = tmp / "config.json"
            cfg.write_text(json.dumps({"db_storage_dir": str(tmp / "db")}))
            script = tmp / "s.sql"
            script.write_text("-- note; with semicolon\nSELECT 'x;y' AS v; -- trailing; comment\n",
                              encoding="utf-8")
            r = subprocess.run([sys.executable, str(HERE / "run_sql.py"), str(script), "--db", "t",
                                "--config", str(cfg)], capture_output=True, text=True, cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("x;y", r.stdout)


if __name__ == "__main__":
    unittest.main()

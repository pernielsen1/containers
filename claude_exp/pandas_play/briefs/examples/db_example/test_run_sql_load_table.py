"""Tests for PRAGMA load_table in run_sql.py: loads a csv/xlsx into the
script's already-open connection, using the same flags as load_table.py's
CLI (minus db selection, since the connection already exists).

Run:  python3 -m unittest test_run_sql_load_table -v   (from db_example/)
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class LoadTablePragmaCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        cfg = self.dir / "config.json"
        cfg.write_text(json.dumps({"db_storage_dir": str(self.dir / "db")}))
        self.cfg = cfg

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel_path, text):
        path = self.dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_script(self, script_path):
        return subprocess.run(
            [sys.executable, str(HERE / "run_sql.py"), str(script_path), "--db", "t", "--config", str(self.cfg)],
            capture_output=True, text=True, cwd=self.dir,
        )


class TestBasic(LoadTablePragmaCase):
    def test_load_then_select_in_same_script(self):
        self.write("a.csv", "key;desc\nk1;one\nk2;two\n")
        script = self.write("s.sql", "PRAGMA load_table = 'a.csv t';\nSELECT * FROM t ORDER BY key;")
        r = self.run_script(script)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("k1", r.stdout)
        self.assertIn("k2", r.stdout)

    def test_with_delimiter_and_decimal_flags(self):
        self.write("a.csv", "key,a_number\nk1,1.5\n")
        script = self.write(
            "s.sql", "PRAGMA load_table = 'a.csv t --delimiter , --decimal .';\nSELECT * FROM t;"
        )
        r = self.run_script(script)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_infile_relative_to_script_directory_not_cwd(self):
        self.write("sub/a.csv", "key;desc\nk1;one\n")
        script = self.write("s.sql", "PRAGMA load_table = 'sub/a.csv t';\nSELECT * FROM t;")
        r = self.run_script(script)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("k1", r.stdout)

    def test_missing_infile_fails_clearly(self):
        script = self.write("s.sql", "PRAGMA load_table = 'nope.csv t';\nSELECT 1;")
        r = self.run_script(script)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("nope.csv", r.stderr)

    def test_missing_table_argument_fails_clearly(self):
        self.write("a.csv", "key;desc\nk1;one\n")
        script = self.write("s.sql", "PRAGMA load_table = 'a.csv';\nSELECT 1;")
        r = self.run_script(script)
        self.assertNotEqual(r.returncode, 0)

    def test_directive_does_not_disturb_last_result_set(self):
        # a SELECT, then a load_table, then --output with no further SELECT
        # should still export the SELECT's result -- load_table isn't a query.
        self.write("a.csv", "key;desc\nk1;one\n")
        script = self.write(
            "s.sql", "SELECT 99 AS x;\nPRAGMA load_table = 'a.csv t';"
        )
        r = subprocess.run(
            [sys.executable, str(HERE / "run_sql.py"), str(script), "--db", "t", "--config", str(self.cfg),
             "--output", str(self.dir / "out.csv")],
            capture_output=True, text=True, cwd=self.dir,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("99", (self.dir / "out.csv").read_text(encoding="utf-8-sig"))


class TestTwoLoadsInOneScript(LoadTablePragmaCase):
    def test_two_pragma_load_table_calls_both_work(self):
        self.write("a.csv", "key;desc\nk1;one\n")
        self.write("b.csv", "key2;desc\nk2;two\n")
        script = self.write(
            "s.sql",
            "PRAGMA load_table = 'a.csv t1';\n"
            "PRAGMA load_table = 'b.csv t2';\n"
            "SELECT t1.key, t2.key2 FROM t1, t2;",
        )
        r = self.run_script(script)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("k1", r.stdout)
        self.assertIn("k2", r.stdout)


class TestDelimiterAliasThroughPragma(LoadTablePragmaCase):
    """The motivating case: a literal ';' delimiter can't survive being
    written inside a PRAGMA value, because run_sql.py splits statements
    on a bare ';' first -- 'PRAGMA load_table = \\'a.csv t --delimiter ;\\';'
    would be truncated mid-statement. The word alias sidesteps that."""

    def test_semi_colon_alias_loads_a_semicolon_delimited_file(self):
        self.write("a.csv", "key,desc\nk1,one\n")  # data still uses ',' on purpose
        script = self.write(
            "s.sql", "PRAGMA load_table = 'a.csv t --delimiter semi_colon';\nSELECT * FROM t;"
        )
        r = self.run_script(script)
        self.assertEqual(r.returncode, 0, r.stderr)
        # delimiter resolved to ';', so the whole "key,desc" line is one column
        self.assertIn("key,desc", r.stdout)


class TestUsableFromAnIncludedScript(LoadTablePragmaCase):
    def test_load_table_inside_an_included_script_resolves_relative_to_it(self):
        self.write("sub/a.csv", "key;desc\nk1;one\n")
        self.write("sub/setup.sql", "PRAGMA load_table = 'a.csv t';")
        script = self.write("mother.sql", "PRAGMA include = 'sub/setup.sql';\nSELECT * FROM t;")
        r = self.run_script(script)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("k1", r.stdout)


if __name__ == "__main__":
    unittest.main()

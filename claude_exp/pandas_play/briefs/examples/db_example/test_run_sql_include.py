"""Tests for PRAGMA include in run_sql.py: splicing another .sql script's
statements in at that point, so a "mother script" can reuse shared setup
(views, formatting) and keep control of its own PRAGMA export.

Run:  python3 -m unittest test_run_sql_include -v   (from db_example/)
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class IncludeCase(unittest.TestCase):
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


class TestBasicInclude(IncludeCase):
    def test_included_statements_run_in_place_and_mother_continues(self):
        self.write("formatting.sql", "CREATE TABLE base(k, v);\nINSERT INTO base VALUES ('a', 1);")
        mother = self.write("mother.sql", "PRAGMA include = 'formatting.sql';\nSELECT * FROM base;")
        r = self.run_script(mother)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("a", r.stdout)
        self.assertIn("1", r.stdout)

    def test_statements_after_include_see_included_objects(self):
        self.write("formatting.sql", "CREATE VIEW my_view AS SELECT 1 AS x;")
        mother = self.write("mother.sql", "PRAGMA include = 'formatting.sql';\nSELECT x + 1 AS y FROM my_view;")
        r = self.run_script(mother)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("2", r.stdout)

    def test_missing_include_file_fails_clearly(self):
        mother = self.write("mother.sql", "PRAGMA include = 'nope.sql';\nSELECT 1;")
        r = self.run_script(mother)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("nope.sql", r.stderr)

    def test_export_inside_included_script_still_fires_in_place(self):
        self.write("formatting.sql", "SELECT 42 AS x;\nPRAGMA export = 'inner.csv';")
        mother = self.write("mother.sql", "PRAGMA include = 'formatting.sql';")
        r = self.run_script(mother)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = (self.dir / "inner.csv").read_text(encoding="utf-8-sig")
        self.assertIn("42", out)

    def test_mother_export_after_include_exports_mothers_own_result(self):
        self.write("formatting.sql", "CREATE VIEW my_view AS SELECT 1 AS x;")
        mother = self.write(
            "mother.sql",
            "PRAGMA include = 'formatting.sql';\nSELECT x + 10 AS y FROM my_view;\nPRAGMA export = 'out.csv';",
        )
        r = self.run_script(mother)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = (self.dir / "out.csv").read_text(encoding="utf-8-sig")
        self.assertIn("11", out)


class TestPathResolution(IncludeCase):
    def test_include_path_relative_to_including_file_not_cwd(self):
        self.write("sub/formatting.sql", "CREATE TABLE base(k);\nINSERT INTO base VALUES ('ok');")
        mother = self.write("mother.sql", "PRAGMA include = 'sub/formatting.sql';\nSELECT * FROM base;")
        r = self.run_script(mother)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ok", r.stdout)

    def test_nested_include_path_relative_to_its_own_file(self):
        # mother -> sub/formatting.sql -> (relative to sub/) helper.sql
        self.write("sub/helper.sql", "CREATE TABLE base(k);\nINSERT INTO base VALUES ('nested');")
        self.write("sub/formatting.sql", "PRAGMA include = 'helper.sql';")
        mother = self.write("mother.sql", "PRAGMA include = 'sub/formatting.sql';\nSELECT * FROM base;")
        r = self.run_script(mother)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("nested", r.stdout)

    def test_udf_extra_inside_included_script_resolves_relative_to_that_script(self):
        self.write("sub/local_udf.py", "def shout(s):\n    return s + '!'\n")
        self.write("sub/extra.csv", "sql_name;module;python_name;num_args;deterministic;path\nshout;local_udf;shout;1;1;\n")
        self.write("sub/formatting.sql", "PRAGMA udf_extra = 'extra.csv';")
        mother = self.write(
            "mother.sql", "PRAGMA include = 'sub/formatting.sql';\nSELECT shout('hi') AS x;"
        )
        r = self.run_script(mother)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("hi!", r.stdout)


class TestCycles(IncludeCase):
    def test_self_include_fails_clearly(self):
        mother = self.write("mother.sql", "PRAGMA include = 'mother.sql';\nSELECT 1;")
        r = self.run_script(mother)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("cycle", r.stderr.lower())

    def test_mutual_include_cycle_fails_clearly(self):
        self.write("a.sql", "PRAGMA include = 'b.sql';")
        self.write("b.sql", "PRAGMA include = 'a.sql';")
        mother = self.write("mother.sql", "PRAGMA include = 'a.sql';\nSELECT 1;")
        r = self.run_script(mother)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("cycle", r.stderr.lower())

    def test_diamond_include_is_not_a_cycle(self):
        # mother includes shared.sql twice via two different includers -- fine, not a cycle
        self.write("shared.sql", "CREATE TABLE IF NOT EXISTS base(k);\nINSERT INTO base VALUES ('x');")
        self.write("left.sql", "PRAGMA include = 'shared.sql';")
        self.write("right.sql", "PRAGMA include = 'shared.sql';")
        mother = self.write(
            "mother.sql",
            "PRAGMA include = 'left.sql';\nPRAGMA include = 'right.sql';\nSELECT COUNT(*) AS n FROM base;",
        )
        r = self.run_script(mother)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("2", r.stdout)


class TestCommentsAndPosition(IncludeCase):
    def test_include_preceded_by_comment_lines(self):
        self.write("formatting.sql", "CREATE TABLE base(k);\nINSERT INTO base VALUES ('c');")
        mother = self.write(
            "mother.sql", "-- header\n-- another\nPRAGMA include = 'formatting.sql';\nSELECT * FROM base;"
        )
        r = self.run_script(mother)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("c", r.stdout)


if __name__ == "__main__":
    unittest.main()

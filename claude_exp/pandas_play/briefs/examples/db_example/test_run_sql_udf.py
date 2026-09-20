"""Tests for run_sql_udf.py (UDF registration from a csv) and the
PRAGMA udf_extra directive in run_sql.py.

Run:  python3 -m unittest test_run_sql_udf -v     (from db_example/)
"""
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SNIPPETS = Path("~/containers/snippets").expanduser()
CSV_HEADER = "sql_name;module;python_name;num_args;deterministic;path\n"

sys.path.insert(0, str(HERE))
import run_sql_udf  # noqa: E402


def write_csv(path, *rows):
    Path(path).write_text(CSV_HEADER + "".join(r + "\n" for r in rows), encoding="utf-8-sig")


class TestRegisterUdfs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.conn = sqlite3.connect(":memory:")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def scalar(self, sql):
        return self.conn.execute(sql).fetchone()[0]

    def test_default_definitions_provide_my_upper(self):
        run_sql_udf.register_udfs(self.conn, run_sql_udf.DEFAULT_UDF_CSV)
        self.assertEqual(self.scalar("SELECT my_upper('abc')"), "ABC")

    def test_my_upper_null_in_null_out(self):
        run_sql_udf.register_udfs(self.conn, run_sql_udf.DEFAULT_UDF_CSV)
        self.assertIsNone(self.scalar("SELECT my_upper(NULL)"))

    def test_module_next_to_csv_needs_no_path_column(self):
        (self.dir / "udf_local_a.py").write_text("def twice(x):\n    return x * 2\n")
        write_csv(self.dir / "u.csv", "twice;udf_local_a;twice;1;1;")
        run_sql_udf.register_udfs(self.conn, self.dir / "u.csv")
        self.assertEqual(self.scalar("SELECT twice(21)"), 42)

    def test_path_column_adds_another_directory_to_sys_path(self):
        other = self.dir / "elsewhere"
        other.mkdir()
        (other / "udf_far_b.py").write_text("def plus_one(x):\n    return x + 1\n")
        write_csv(self.dir / "u.csv", f"plus_one;udf_far_b;plus_one;1;1;{other}")
        run_sql_udf.register_udfs(self.conn, self.dir / "u.csv")
        self.assertEqual(self.scalar("SELECT plus_one(1)"), 2)

    def test_num_args_is_honoured(self):
        (self.dir / "udf_local_c.py").write_text("def add_two(a, b):\n    return a + b\n")
        write_csv(self.dir / "u.csv", "add_two;udf_local_c;add_two;2;1;")
        run_sql_udf.register_udfs(self.conn, self.dir / "u.csv")
        self.assertEqual(self.scalar("SELECT add_two(1, 2)"), 3)
        with self.assertRaises(sqlite3.OperationalError):
            self.scalar("SELECT add_two(1)")

    def test_dict_result_becomes_json_text(self):
        (self.dir / "udf_local_d.py").write_text("def info(s):\n    return {'ok': True, 'n': len(s)}\n")
        write_csv(self.dir / "u.csv", "info;udf_local_d;info;1;1;")
        run_sql_udf.register_udfs(self.conn, self.dir / "u.csv")
        self.assertEqual(json.loads(self.scalar("SELECT info('abc')")), {"ok": True, "n": 3})
        self.assertEqual(self.scalar("SELECT json_extract(info('abc'), '$.n')"), 3)

    def test_unknown_function_gives_clear_error(self):
        (self.dir / "udf_local_e.py").write_text("def real():\n    return 1\n")
        write_csv(self.dir / "u.csv", "nope;udf_local_e;does_not_exist;0;1;")
        with self.assertRaises(SystemExit) as cm:
            run_sql_udf.register_udfs(self.conn, self.dir / "u.csv")
        self.assertIn("does_not_exist", str(cm.exception))

    def test_missing_csv_gives_clear_error(self):
        with self.assertRaises(SystemExit) as cm:
            run_sql_udf.register_udfs(self.conn, self.dir / "missing.csv")
        self.assertIn("missing.csv", str(cm.exception))


@unittest.skipUnless((SNIPPETS / "company_identifiers.py").exists(), "snippets/company_identifiers.py not found")
class TestCompanyIdExample(unittest.TestCase):
    """Part 3: a class living in another directory tree, reached via the csv path column."""

    def test_validate_company_id_udf(self):
        conn = sqlite3.connect(":memory:")
        run_sql_udf.register_udfs(conn, HERE / "samples" / "udf_extra.csv")
        raw = conn.execute("SELECT validate_COMPANY_ID('12345674', 'DK')").fetchone()[0]
        self.assertTrue(json.loads(raw)["validation_result"])
        bad = conn.execute("SELECT json_extract(validate_COMPANY_ID('12345675', 'DK'), '$.validation_result')").fetchone()[0]
        self.assertEqual(bad, 0)
        conn.close()


class TestRunSqlEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        cfg = self.dir / "config.json"
        cfg.write_text(json.dumps({"db_storage_dir": str(self.dir / "db")}))
        self.cfg = cfg

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, sql_text):
        script = self.dir / "s.sql"
        script.write_text(sql_text, encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(HERE / "run_sql.py"), str(script), "--db", "t", "--config", str(self.cfg)],
            capture_output=True, text=True, cwd=self.dir,
        )

    def test_default_udf_available_without_any_pragma(self):
        r = self.run_script("SELECT my_upper('abc') AS x;")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ABC", r.stdout)

    def test_udf_extra_relative_to_script_dir(self):
        (self.dir / "udf_local_f.py").write_text("def shout(s):\n    return s + '!'\n")
        write_csv(self.dir / "extra.csv", "shout;udf_local_f;shout;1;1;")
        r = self.run_script("PRAGMA udf_extra = 'extra.csv';\nSELECT shout('hi') AS x;")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("hi!", r.stdout)

    def test_udf_extra_registered_even_if_pragma_comes_after_first_statement_position(self):
        # pragma is pre-scanned, so its position in the script does not matter
        (self.dir / "udf_local_g.py").write_text("def shout(s):\n    return s + '!'\n")
        write_csv(self.dir / "extra.csv", "shout;udf_local_g;shout;1;1;")
        r = self.run_script("SELECT 1;\nPRAGMA udf_extra = 'extra.csv';\nSELECT shout('yo') AS x;")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("yo!", r.stdout)

    def test_pragma_preceded_by_comment_lines(self):
        (self.dir / "udf_local_h.py").write_text("def shout(s):\n    return s + '!'\n")
        write_csv(self.dir / "extra.csv", "shout;udf_local_h;shout;1;1;")
        r = self.run_script("-- header comment\n-- another\nPRAGMA udf_extra = 'extra.csv';\nSELECT shout('c') AS x;")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("c!", r.stdout)

    def test_udf_extra_missing_file_fails_clearly(self):
        r = self.run_script("PRAGMA udf_extra = 'nope.csv';\nSELECT 1;")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("nope.csv", r.stderr)


if __name__ == "__main__":
    unittest.main()

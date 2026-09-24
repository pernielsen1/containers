"""Tests for PRAGMA print in run_sql.py: a plain console message at
that point in the script -- e.g. instructions for a manual next step.

Run:  python3 -m unittest test_run_sql_print -v   (from db_example/)
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class PrintCase(unittest.TestCase):
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

    def run_script(self, sql_text, **extra_run_kwargs):
        script = self.write("s.sql", sql_text)
        return subprocess.run(
            [sys.executable, str(HERE / "run_sql.py"), str(script), "--db", "t", "--config", str(self.cfg)],
            capture_output=True, text=True, cwd=self.dir, **extra_run_kwargs,
        )


class TestPragmaPrint(PrintCase):
    def test_message_is_printed(self):
        r = self.run_script("PRAGMA print = 'now open the export and check totals';\nSELECT 1;")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("now open the export and check totals", r.stdout)

    def test_printed_before_a_later_statements_output(self):
        r = self.run_script(
            "PRAGMA print = 'about to select';\nSELECT 42 AS x;"
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        pos_msg = r.stdout.index("about to select")
        pos_result = r.stdout.index("42")
        self.assertLess(pos_msg, pos_result)

    def test_multiple_print_directives_appear_in_order(self):
        r = self.run_script(
            "PRAGMA print = 'step one';\nPRAGMA print = 'step two';\nSELECT 1;"
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(r.stdout.index("step one"), r.stdout.index("step two"))

    def test_does_not_disturb_last_result_set(self):
        r = subprocess.run(
            [sys.executable, str(HERE / "run_sql.py"),
             str(self.write("s.sql", "SELECT 7 AS x;\nPRAGMA print = 'done loading';")),
             "--db", "t", "--config", str(self.cfg), "--output", str(self.dir / "out.csv")],
            capture_output=True, text=True, cwd=self.dir,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("7", (self.dir / "out.csv").read_text(encoding="utf-8-sig"))

    def test_preceded_by_comment_lines(self):
        r = self.run_script("-- heads up\nPRAGMA print = 'reminder';\nSELECT 1;")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("reminder", r.stdout)

    def test_print_inside_an_included_script(self):
        self.write("included.sql", "PRAGMA print = 'from the include';")
        r = self.run_script("PRAGMA include = 'included.sql';\nSELECT 1;")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("from the include", r.stdout)


if __name__ == "__main__":
    unittest.main()

"""Tests for PRAGMA export's optional --sheet flag in run_sql.py:
xlsx only; a plain export (no --sheet) still overwrites the whole file
each time, naming a sheet instead appends that sheet to the workbook
at that path (even across an included child script), and repeating
the same path+sheet in one run is an error.

Run:  python3 -m unittest test_run_sql_export_sheets -v   (from db_example/)
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent


class ExportSheetsCase(unittest.TestCase):
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


class TestExportSheets(ExportSheetsCase):
    def test_plain_export_still_overwrites_whole_file(self):
        out = self.dir / "out.xlsx"
        r = self.run_script(
            f"SELECT 1 AS x;\nPRAGMA export = '{out}';\nSELECT 2 AS x;\nPRAGMA export = '{out}';"
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        sheets = pd.read_excel(out, sheet_name=None)
        self.assertEqual(list(sheets.keys()), ["Sheet1"])
        self.assertEqual(sheets["Sheet1"]["x"].tolist(), [2])

    def test_two_sheet_names_build_one_workbook(self):
        out = self.dir / "out.xlsx"
        r = self.run_script(
            f"SELECT 1 AS x;\nPRAGMA export = '{out} --sheet Totals';\n"
            f"SELECT 2 AS x;\nPRAGMA export = '{out} --sheet Detail';"
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        sheets = pd.read_excel(out, sheet_name=None)
        self.assertEqual(set(sheets.keys()), {"Totals", "Detail"})
        self.assertEqual(sheets["Totals"]["x"].tolist(), [1])
        self.assertEqual(sheets["Detail"]["x"].tolist(), [2])

    def test_included_child_script_adds_a_sheet_to_mother_workbook(self):
        out = self.dir / "out.xlsx"
        self.write("child.sql", f"SELECT 2 AS x;\nPRAGMA export = '{out} --sheet Detail';")
        r = self.run_script(
            f"SELECT 1 AS x;\nPRAGMA export = '{out} --sheet Totals';\nPRAGMA include = 'child.sql';"
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        sheets = pd.read_excel(out, sheet_name=None)
        self.assertEqual(set(sheets.keys()), {"Totals", "Detail"})

    def test_repeated_path_and_sheet_is_an_error(self):
        out = self.dir / "out.xlsx"
        r = self.run_script(
            f"SELECT 1 AS x;\nPRAGMA export = '{out} --sheet Totals';\n"
            f"SELECT 2 AS x;\nPRAGMA export = '{out} --sheet Totals';"
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Totals", r.stderr)

    def test_sheet_flag_on_csv_is_rejected(self):
        out = self.dir / "out.csv"
        r = self.run_script(f"SELECT 1 AS x;\nPRAGMA export = '{out} --sheet Totals';")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--sheet", r.stderr)

    def test_wrote_message_mentions_sheet(self):
        out = self.dir / "out.xlsx"
        r = self.run_script(f"SELECT 1 AS x;\nPRAGMA export = '{out} --sheet Totals';")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"wrote 1 rows -> {out}#Totals", r.stdout)


if __name__ == "__main__":
    unittest.main()

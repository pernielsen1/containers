"""Tests for load_table.py's --encoding / --delimiter / --decimal options.

Run:  python3 -m unittest test_load_table -v     (from db_example/)

Uses table "table_1" because field_definitions.csv already types its
a_number column as float.
"""
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class LoadTableCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = self.dir / "config.json"
        self.cfg.write_text(json.dumps({"db_storage_dir": str(self.dir / "db")}))

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text, encoding="utf-8"):
        path = self.dir / name
        path.write_bytes(text.encode(encoding))
        return path

    def load(self, infile, *extra):
        return subprocess.run(
            [sys.executable, str(HERE / "load_table.py"), str(infile), "t", "table_1", "--config", str(self.cfg), *extra],
            capture_output=True, text=True,
        )

    def rows(self):
        conn = sqlite3.connect(self.dir / "db" / "t.db")
        try:
            return conn.execute("SELECT * FROM table_1 ORDER BY 1").fetchall()
        finally:
            conn.close()

    def columns(self):
        conn = sqlite3.connect(self.dir / "db" / "t.db")
        try:
            return [r[1] for r in conn.execute("PRAGMA table_info(table_1)")]
        finally:
            conn.close()


class TestDefaults(LoadTableCase):
    def test_default_semicolon_plain_utf8(self):
        f = self.write("a.csv", "key;a_number\nÆble;1.5\n")
        r = self.load(f)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rows(), [("Æble", 1.5)])

    def test_default_strips_bom_from_first_column_name(self):
        f = self.write("a.csv", "﻿key;a_number\nk;2\n")
        r = self.load(f)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.columns(), ["key", "a_number"])


class TestDelimiter(LoadTableCase):
    def test_comma_delimiter(self):
        f = self.write("a.csv", "key,a_number\nk,3.5\n")
        r = self.load(f, "--delimiter", ",")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rows(), [("k", 3.5)])

    def test_tab_delimiter_escape(self):
        f = self.write("a.csv", "key\ta_number\nk\t4.5\n")
        r = self.load(f, "--delimiter", "\\t")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rows(), [("k", 4.5)])

    def test_wrong_delimiter_fails_on_unknown_column(self):
        # whole header lands in one column -> field_definitions check catches it
        f = self.write("a.csv", "key,a_number\nk,3.5\n")
        r = self.load(f)
        self.assertNotEqual(r.returncode, 0)


class TestEncoding(LoadTableCase):
    def test_latin1(self):
        f = self.write("a.csv", "key;a_number\nÆble;1\n", encoding="latin-1")
        r = self.load(f, "--encoding", "latin-1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rows(), [("Æble", 1.0)])

    def test_wrong_encoding_is_an_error_not_garbage(self):
        f = self.write("a.csv", "key;a_number\nÆble;1\n", encoding="latin-1")
        r = self.load(f)  # default utf-8-sig cannot decode 0xC6
        self.assertNotEqual(r.returncode, 0)


class TestDecimal(LoadTableCase):
    def test_default_accepts_comma_decimal(self):
        f = self.write("a.csv", "key;a_number\nk;1,5\n")
        r = self.load(f)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rows(), [("k", 1.5)])

    def test_default_still_accepts_dot_decimal(self):
        f = self.write("a.csv", "key;a_number\nk;1.5\n")
        r = self.load(f)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rows(), [("k", 1.5)])

    def test_explicit_dot_rejects_comma_decimal(self):
        f = self.write("a.csv", "key;a_number\nk;1,5\n")
        r = self.load(f, "--decimal", ".")
        self.assertNotEqual(r.returncode, 0)

    def test_comma_delimiter_with_quoted_comma_decimal(self):
        f = self.write("a.csv", 'key,a_number\nk,"1,5"\n')
        r = self.load(f, "--delimiter", ",", "--decimal", ",")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rows(), [("k", 1.5)])

    def test_decimal_must_be_single_char(self):
        f = self.write("a.csv", "key;a_number\nk;1\n")
        r = self.load(f, "--decimal", ",,")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("decimal", r.stderr)


class TestCsvOnlyOptionsOnXlsx(LoadTableCase):
    def test_options_rejected_for_xlsx(self):
        import pandas as pd
        f = self.dir / "a.xlsx"
        pd.DataFrame({"key": ["k"], "a_number": [1.5]}).to_excel(f, index=False)
        for opt, val in (("--encoding", "latin-1"), ("--delimiter", ","), ("--decimal", ",")):
            r = self.load(f, opt, val)
            self.assertNotEqual(r.returncode, 0, opt)
            self.assertIn(opt, r.stderr)

    def test_xlsx_still_loads_without_options(self):
        import pandas as pd
        f = self.dir / "a.xlsx"
        pd.DataFrame({"key": ["k"], "a_number": [1.5]}).to_excel(f, index=False)
        r = self.load(f)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rows(), [("k", 1.5)])


if __name__ == "__main__":
    unittest.main()

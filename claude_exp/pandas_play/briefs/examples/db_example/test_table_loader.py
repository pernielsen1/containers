"""Tests for the TableLoader class in load_table.py (the refactor that
lets PRAGMA load_table -- and any other caller with an open connection
-- reuse the same load logic as the CLI without re-resolving db/env).

Run:  python3 -m unittest test_table_loader -v   (from db_example/)
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from load_table import TableLoader


class TableLoaderCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.conn = sqlite3.connect(":memory:")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def rows(self, table):
        return self.conn.execute(f'SELECT * FROM "{table}" ORDER BY 1').fetchall()


class TestLoadBasics(TableLoaderCase):
    def test_load_returns_row_count_and_loads_table(self):
        f = self.write("a.csv", "key;desc\nk1;one\nk2;two\n")
        loader = TableLoader(field_definitions_path=self.dir / "field_definitions.csv")
        n = loader.load(self.conn, f, "t")
        self.assertEqual(n, 2)
        self.assertEqual(self.rows("t"), [("k1", "one"), ("k2", "two")])

    def test_reload_drops_existing_table_first(self):
        f1 = self.write("a.csv", "key;desc\nk1;one\n")
        f2 = self.write("b.csv", "key;desc\nk2;two\nk3;three\n")
        loader = TableLoader(field_definitions_path=self.dir / "field_definitions.csv")
        loader.load(self.conn, f1, "t")
        loader.load(self.conn, f2, "t")
        self.assertEqual(self.rows("t"), [("k2", "two"), ("k3", "three")])

    def test_missing_infile_raises_systemexit(self):
        loader = TableLoader(field_definitions_path=self.dir / "field_definitions.csv")
        with self.assertRaises(SystemExit) as cm:
            loader.load(self.conn, self.dir / "nope.csv", "t")
        self.assertIn("nope.csv", str(cm.exception))

    def test_unsupported_suffix_raises_systemexit(self):
        f = self.write("a.txt", "key;desc\nk1;one\n")
        loader = TableLoader(field_definitions_path=self.dir / "field_definitions.csv")
        with self.assertRaises(SystemExit):
            loader.load(self.conn, f, "t")

    def test_typed_column_from_field_definitions(self):
        self.write("field_definitions.csv", "table;field;type;sql_column_name\nt;a_number;float;\n")
        f = self.write("a.csv", "key;a_number\nk1;1,5\n")
        loader = TableLoader(field_definitions_path=self.dir / "field_definitions.csv")
        loader.load(self.conn, f, "t")
        self.assertEqual(self.rows("t"), [("k1", 1.5)])


class TestDelimiterAliases(TableLoaderCase):
    """Named aliases (case-insensitive) so a delimiter that would
    otherwise be awkward to write -- ';' above all, since run_sql.py
    splits statements on a bare ';' and would truncate a PRAGMA
    load_table value containing one -- can be spelled as a word."""

    def test_semi_colon_alias(self):
        f = self.write("a.csv", "key,desc\nk1,one\n")
        loader = TableLoader(field_definitions_path=self.dir / "field_definitions.csv")
        loader.load(self.conn, f, "t", delimiter="semi_colon")
        # data uses ',' -- with delimiter resolved to ';' the whole line is one column
        self.assertEqual(self.rows("t"), [("k1,one",)])

    def test_alias_is_case_insensitive(self):
        f = self.write("a.csv", "key;desc\nk1;one\n")
        loader = TableLoader(field_definitions_path=self.dir / "field_definitions.csv")
        loader.load(self.conn, f, "t", delimiter="SEMI_COLON")
        self.assertEqual(self.rows("t"), [("k1", "one")])

    def test_comma_and_tab_and_pipe_aliases(self):
        loader = TableLoader(field_definitions_path=self.dir / "field_definitions.csv")
        f = self.write("comma.csv", "key,desc\nk1,one\n")
        loader.load(self.conn, f, "t_comma", delimiter="comma")
        self.assertEqual(self.rows("t_comma"), [("k1", "one")])

        f = self.write("tab.csv", "key\tdesc\nk1\tone\n")
        loader.load(self.conn, f, "t_tab", delimiter="tab")
        self.assertEqual(self.rows("t_tab"), [("k1", "one")])

        f = self.write("pipe.csv", "key|desc\nk1|one\n")
        loader.load(self.conn, f, "t_pipe", delimiter="pipe")
        self.assertEqual(self.rows("t_pipe"), [("k1", "one")])

    def test_backslash_t_still_works_alongside_aliases(self):
        f = self.write("a.csv", "key\tdesc\nk1\tone\n")
        loader = TableLoader(field_definitions_path=self.dir / "field_definitions.csv")
        loader.load(self.conn, f, "t", delimiter="\\t")
        self.assertEqual(self.rows("t"), [("k1", "one")])

    def test_literal_single_character_still_works(self):
        f = self.write("a.csv", "key|desc\nk1|one\n")
        loader = TableLoader(field_definitions_path=self.dir / "field_definitions.csv")
        loader.load(self.conn, f, "t", delimiter="|")
        self.assertEqual(self.rows("t"), [("k1", "one")])

    def test_unknown_multi_char_delimiter_still_rejected(self):
        f = self.write("a.csv", "key;desc\nk1;one\n")
        loader = TableLoader(field_definitions_path=self.dir / "field_definitions.csv")
        with self.assertRaises(SystemExit):
            loader.load(self.conn, f, "t", delimiter="nonsense")


class TestXlsxOptionRejection(TableLoaderCase):
    def test_csv_only_options_rejected_for_xlsx(self):
        import pandas as pd
        f = self.dir / "a.xlsx"
        pd.DataFrame({"key": ["k"]}).to_excel(f, index=False)
        loader = TableLoader(field_definitions_path=self.dir / "field_definitions.csv")
        for kwargs in ({"encoding": "latin-1"}, {"delimiter": ","}, {"decimal": ","}):
            with self.assertRaises(SystemExit):
                loader.load(self.conn, f, "t", **kwargs)


class TestFieldDefinitionsCaching(TableLoaderCase):
    def test_field_definitions_file_read_only_once_across_multiple_loads(self):
        self.write("field_definitions.csv", "table;field;type;sql_column_name\nt1;a_number;float;\nt2;a_number;int;\n")
        f1 = self.write("a.csv", "key;a_number\nk1;1.5\n")
        f2 = self.write("b.csv", "key;a_number\nk2;3\n")
        loader = TableLoader(field_definitions_path=self.dir / "field_definitions.csv")

        read_count = {"n": 0}
        original = loader._read_field_definitions

        def counting_read():
            read_count["n"] += 1
            return original()

        loader._read_field_definitions = counting_read

        loader.load(self.conn, f1, "t1")
        loader.load(self.conn, f2, "t2")

        self.assertEqual(read_count["n"], 1)
        self.assertEqual(self.rows("t1"), [("k1", 1.5)])
        self.assertEqual(self.rows("t2"), [("k2", 3)])

    def test_no_field_definitions_file_means_everything_stays_text(self):
        f = self.write("a.csv", "key;a_number\nk1;1.5\n")
        loader = TableLoader(field_definitions_path=self.dir / "does_not_exist.csv")
        loader.load(self.conn, f, "t")
        self.assertEqual(self.rows("t"), [("k1", "1.5")])


if __name__ == "__main__":
    unittest.main()

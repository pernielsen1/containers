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


class TestDefaultFieldDefinitions(TableLoaderCase):
    """A field_definitions.csv row with a blank table ('' -- e.g.
    ';my_key;int;') sets a default type/rename for any field with that
    name, across every table, unless a table-specific row for that
    exact (table, field) exists -- which then wins outright for that
    field (not merged column-by-column with the default)."""

    def test_default_applies_when_no_table_specific_row(self):
        self.write("field_definitions.csv", "table;field;type;sql_column_name\n;my_key;int;\n")
        f = self.write("a.csv", "my_key;desc\n7;x\n")
        loader = TableLoader(field_definitions_path=self.dir / "field_definitions.csv")
        loader.load(self.conn, f, "t")
        self.assertEqual(self.rows("t"), [(7, "x")])

    def test_default_applies_across_multiple_unrelated_tables(self):
        self.write("field_definitions.csv", "table;field;type;sql_column_name\n;my_key;int;\n")
        loader = TableLoader(field_definitions_path=self.dir / "field_definitions.csv")
        f1 = self.write("a.csv", "my_key;desc\n1;x\n")
        f2 = self.write("b.csv", "my_key;desc\n2;y\n")
        loader.load(self.conn, f1, "t1")
        loader.load(self.conn, f2, "t2")
        self.assertEqual(self.rows("t1"), [(1, "x")])
        self.assertEqual(self.rows("t2"), [(2, "y")])

    def test_table_specific_row_overrides_default_type(self):
        self.write(
            "field_definitions.csv",
            "table;field;type;sql_column_name\n;my_key;int;\ntable_with_str_my_key;my_key;str;\n",
        )
        loader = TableLoader(field_definitions_path=self.dir / "field_definitions.csv")
        f = self.write("a.csv", "my_key;desc\n007;x\n")
        loader.load(self.conn, f, "table_with_str_my_key")
        # int default would strip the leading zero -- str override keeps it as text
        self.assertEqual(self.rows("table_with_str_my_key"), [("007", "x")])

    def test_table_specific_override_is_not_merged_with_default(self):
        # default sets type=int and a rename; table-specific row sets only
        # a different type -- the override is total, not per-column merge,
        # so this table's column keeps the ORIGINAL field name, not the default's rename.
        self.write(
            "field_definitions.csv",
            "table;field;type;sql_column_name\n"
            ";my_key;int;renamed_key\n"
            "t_override;my_key;float;\n",
        )
        loader = TableLoader(field_definitions_path=self.dir / "field_definitions.csv")
        f = self.write("a.csv", "my_key;desc\n1.5;x\n")
        loader.load(self.conn, f, "t_override")
        cols = [r[1] for r in self.conn.execute('PRAGMA table_info("t_override")')]
        self.assertEqual(cols, ["my_key", "desc"])
        self.assertEqual(self.rows("t_override"), [(1.5, "x")])

    def test_default_rename_applies_when_table_has_no_override(self):
        self.write("field_definitions.csv", "table;field;type;sql_column_name\n;my_key;int;renamed_key\n")
        loader = TableLoader(field_definitions_path=self.dir / "field_definitions.csv")
        f = self.write("a.csv", "my_key;desc\n1;x\n")
        loader.load(self.conn, f, "t")
        cols = [r[1] for r in self.conn.execute('PRAGMA table_info("t")')]
        self.assertEqual(cols, ["renamed_key", "desc"])

    def test_unrelated_field_in_same_table_stays_plain_text(self):
        self.write("field_definitions.csv", "table;field;type;sql_column_name\n;my_key;int;\n")
        loader = TableLoader(field_definitions_path=self.dir / "field_definitions.csv")
        f = self.write("a.csv", "my_key;other_field\n1;9\n")
        loader.load(self.conn, f, "t")
        self.assertEqual(self.rows("t"), [(1, "9")])

    def test_default_field_absent_from_this_table_is_silently_ignored(self):
        # the default doesn't have to apply everywhere -- a table whose
        # csv simply has no "my_key" column shouldn't error.
        self.write("field_definitions.csv", "table;field;type;sql_column_name\n;my_key;int;\n")
        loader = TableLoader(field_definitions_path=self.dir / "field_definitions.csv")
        f = self.write("a.csv", "key;desc\nk1;one\n")
        loader.load(self.conn, f, "t")
        self.assertEqual(self.rows("t"), [("k1", "one")])

    def test_table_specific_row_for_a_missing_column_still_errors(self):
        # unlike a default, a table's OWN row naming a column that
        # isn't in its csv is still a real (likely typo) error.
        self.write("field_definitions.csv", "table;field;type;sql_column_name\nt;does_not_exist;int;\n")
        loader = TableLoader(field_definitions_path=self.dir / "field_definitions.csv")
        f = self.write("a.csv", "key;desc\nk1;one\n")
        with self.assertRaises(SystemExit) as cm:
            loader.load(self.conn, f, "t")
        self.assertIn("does_not_exist", str(cm.exception))

    def test_unknown_type_in_a_default_row_is_reported(self):
        self.write("field_definitions.csv", "table;field;type;sql_column_name\n;my_key;bogus;\n")
        loader = TableLoader(field_definitions_path=self.dir / "field_definitions.csv")
        f = self.write("a.csv", "my_key;desc\n1;x\n")
        with self.assertRaises(SystemExit) as cm:
            loader.load(self.conn, f, "t")
        self.assertIn("bogus", str(cm.exception))


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

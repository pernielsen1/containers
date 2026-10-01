"""Tests for anacredit_postal_code.py (AnaCredit section 4.5 postal code
formats) and its registration as UDFs in run_sql.py.

Run:  python3 -m unittest test_anacredit_postal_code -v     (from db_example/)
"""
import csv
import sqlite3
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import anacredit_postal_code  # noqa: E402
import run_sql_udf  # noqa: E402
from anacredit_postal_code import AnaCredit_PostalCode  # noqa: E402


class TestFormatsCsv(unittest.TestCase):
    def test_csv_has_header_and_158_countries(self):
        with open(HERE / "postal_code_formats.csv", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f, delimiter=";"))
        self.assertEqual(list(rows[0]), ["country", "rule", "pattern"])
        self.assertEqual(len(rows), 158)
        self.assertEqual(len({r["country"] for r in rows}), 158)


class TestValidate(unittest.TestCase):
    def setUp(self):
        self.pc = AnaCredit_PostalCode()

    def test_sweden_needs_blank(self):
        self.assertTrue(self.pc.validate("123 45", "SE"))
        self.assertFalse(self.pc.validate("12345", "SE"))
        self.assertFalse(self.pc.validate("023 45", "SE"))

    def test_germany_five_digits(self):
        self.assertTrue(self.pc.validate("12345", "DE"))
        self.assertFalse(self.pc.validate("123 45", "DE"))
        self.assertFalse(self.pc.validate("1234", "DE"))

    def test_full_match_not_search(self):
        self.assertFalse(self.pc.validate("x12345", "DE"))
        self.assertFalse(self.pc.validate("12345 ", "DE"))

    def test_alternatives_malta_and_us(self):
        self.assertTrue(self.pc.validate("ABC 1234", "MT"))
        self.assertTrue(self.pc.validate("12345-6789", "US"))
        self.assertTrue(self.pc.validate("12345", "US"))

    def test_country_without_rule_is_valid(self):
        self.assertTrue(self.pc.validate("SW1A 1AA", "GB"))

    def test_country_case_and_blanks_tolerated(self):
        self.assertTrue(self.pc.validate("12345", " de "))

    def test_null_in_null_out(self):
        self.assertIsNone(self.pc.validate(None, "DE"))
        self.assertIsNone(self.pc.validate("12345", None))

    def test_returns_real_bool(self):
        self.assertIs(self.pc.validate("12345", "DE"), True)
        self.assertIs(self.pc.validate("1", "DE"), False)


class TestVerbosed(unittest.TestCase):
    def setUp(self):
        self.pc = AnaCredit_PostalCode()

    def test_sweden_inserts_blank(self):
        self.assertEqual(self.pc.verbosed("12345", "SE"), "123 45")

    def test_sweden_replaces_wrong_separator_and_extra_noise(self):
        self.assertEqual(self.pc.verbosed("123-45", "SE"), "123 45")
        self.assertEqual(self.pc.verbosed(" 123   45 ", "SE"), "123 45")

    def test_inserts_dash(self):
        self.assertEqual(self.pc.verbosed("12345", "PL"), "12-345")
        self.assertEqual(self.pc.verbosed("1234567", "JP"), "123-4567")
        self.assertEqual(self.pc.verbosed("1234567", "PT"), "1234-567")

    def test_germany_strips_blank(self):
        self.assertEqual(self.pc.verbosed("123 45", "DE"), "12345")

    def test_fixed_values(self):
        self.assertEqual(self.pc.verbosed("ai2640", "AI"), "AI-2640")
        self.assertEqual(self.pc.verbosed("gx111aa", "GI"), "GX11 1AA")

    def test_already_valid_unchanged(self):
        self.assertEqual(self.pc.verbosed("123 45", "SE"), "123 45")
        self.assertEqual(self.pc.verbosed("12345-6789", "US"), "12345-6789")

    def test_lowercase_uppercased(self):
        self.assertEqual(self.pc.verbosed("1234ab", "NL"), "1234AB")

    def test_cannot_be_fixed_gives_none(self):
        self.assertIsNone(self.pc.verbosed("ABCDE", "SE"))
        self.assertIsNone(self.pc.verbosed("1234", "DE"))

    def test_country_without_rule_returned_stripped(self):
        self.assertEqual(self.pc.verbosed(" SW1A 1AA ", "GB"), "SW1A 1AA")

    def test_null_in_null_out(self):
        self.assertIsNone(self.pc.verbosed(None, "SE"))
        self.assertIsNone(self.pc.verbosed("12345", None))

    def test_verbosed_result_always_validates(self):
        for zip_, country in [("12345", "SE"), ("12345", "PL"), ("1234ab", "NL"), ("96912", "GU")]:
            self.assertTrue(self.pc.validate(self.pc.verbosed(zip_, country), country))


class TestUdfRegistration(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        run_sql_udf.register_udfs(self.conn, run_sql_udf.DEFAULT_UDF_CSV)

    def tearDown(self):
        self.conn.close()

    def scalar(self, sql):
        return self.conn.execute(sql).fetchone()[0]

    def test_valid_udf(self):
        self.assertEqual(self.scalar("SELECT anacredit_postal_valid('123 45', 'SE')"), 1)
        self.assertEqual(self.scalar("SELECT anacredit_postal_valid('12345', 'SE')"), 0)

    def test_verbosed_udf(self):
        self.assertEqual(self.scalar("SELECT anacredit_postal_verbosed('12345', 'SE')"), "123 45")

    def test_udfs_null_handling(self):
        self.assertIsNone(self.scalar("SELECT anacredit_postal_valid(NULL, 'SE')"))
        self.assertIsNone(self.scalar("SELECT anacredit_postal_verbosed('12345', NULL)"))

    def test_udf_usable_over_a_table(self):
        self.conn.execute("CREATE TABLE cp (zip TEXT, country TEXT)")
        self.conn.executemany("INSERT INTO cp VALUES (?, ?)",
                              [("123 45", "SE"), ("12345", "SE"), ("12345", "DE")])
        n = self.scalar("SELECT COUNT(*) FROM cp WHERE anacredit_postal_valid(zip, country) = 0")
        self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()

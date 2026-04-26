"""
tests/test_catalogue.py
Tests for the Catalogue loader and CalculationEngine.
Run from anywhere: pytest bista_v2/tests/test_catalogue.py
"""

import sys
from pathlib import Path
import pytest

# Add project root to path so we can import annex_bista
PROJECT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT))

from annex_bista import Catalogue, CalculationEngine


CATALOGUE_DIR = PROJECT  # bista_fields.csv and bista_calcs.csv live here


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def cat():
    return Catalogue(CATALOGUE_DIR)


@pytest.fixture(scope="module")
def engine(cat):
    return CalculationEngine(cat)


# ── Catalogue loading ─────────────────────────────────────────────────────────

def test_fields_csv_loads(cat):
    assert len(cat.fields) > 100, "Expected 100+ fields in catalogue"


def test_calcs_csv_loads(cat):
    assert len(cat.calcs) > 10, "Expected 10+ calc rules in catalogue"


def test_known_input_field_s11(cat):
    assert cat.fields.get(("S11", "061")) == "input"


def test_known_input_field_s11_176(cat):
    assert cat.fields.get(("S11", "176")) == "input"


def test_known_calculate_field_s11_060(cat):
    assert cat.fields.get(("S11", "060")) == "calculate"


def test_known_calculate_field_s11_180(cat):
    assert cat.fields.get(("S11", "180")) == "calculate"


def test_known_calculate_field_s21_330(cat):
    assert cat.fields.get(("S21", "330")) == "calculate"


def test_known_calculate_field_s21_310(cat):
    assert cat.fields.get(("S21", "310")) == "calculate"


def test_b7_input_field(cat):
    assert cat.fields.get(("B7", "114/02")) == "input"


def test_b7_calculate_total_row(cat):
    assert cat.fields.get(("B7", "120/02")) == "calculate"


def test_a1_input_field(cat):
    assert cat.fields.get(("A1", "111/01")) == "input"


def test_a1_calculate_row(cat):
    assert cat.fields.get(("A1", "100/01")) == "calculate"


def test_nil_field(cat):
    assert cat.fields.get(("S11", "030")) == "nil"


# ── Calc formula content ──────────────────────────────────────────────────────

def test_s11_060_formula(cat):
    formula = cat.calcs.get(("S11", "060"))
    assert formula is not None
    assert "061" in formula and "062" in formula


def test_s11_180_formula(cat):
    formula = cat.calcs.get(("S11", "180"))
    assert formula is not None
    assert "010" in formula
    assert "170" in formula


def test_s21_310_formula(cat):
    formula = cat.calcs.get(("S21", "310"))
    assert formula is not None
    assert "311" in formula and "312" in formula and "313" in formula


def test_s21_330_formula(cat):
    formula = cat.calcs.get(("S21", "330"))
    assert formula is not None
    assert "210" in formula and "310" in formula


def test_b7_120_col02_formula(cat):
    formula = cat.calcs.get(("B7", "120/02"))
    assert formula is not None
    assert "121/02" in formula and "122/02" in formula and "123/02" in formula


def test_a1_110_col01_formula(cat):
    formula = cat.calcs.get(("A1", "110/01"))
    assert formula is not None
    assert "111/01" in formula and "114/01" in formula


# ── Calculation engine — simple cases ────────────────────────────────────────

def test_engine_s11_060(engine):
    data = {("S11", "061"): 10_000_000, ("S11", "062"): 500_000}
    result, _ = engine.apply(data)
    assert result[("S11", "060")] == 10_500_000


def test_engine_s11_070(engine):
    data = {("S11", "071"): 120_000_000}
    result, _ = engine.apply(data)
    assert result[("S11", "070")] == 120_000_000  # 071 + 072=0


def test_engine_s11_180_chain(engine):
    """S11/180 depends on 060 which depends on 061 — chain resolution."""
    data = {
        ("S11", "020"): 2_000_000,
        ("S11", "061"): 40_000_000,
        ("S11", "071"): 120_000_000,
        ("S11", "140"): 2_000_000,
        ("S11", "176"): 4_000_000,
    }
    result, _ = engine.apply(data)
    # 060 = 061 + 062(0) = 40M
    assert result[("S11", "060")] == 40_000_000
    # 070 = 071 + 072(0) = 120M
    assert result[("S11", "070")] == 120_000_000
    # 180 = 020 + 060 + 070 + 140 + 170(=176) = 2+40+120+2+4 = 168M
    assert result[("S11", "180")] == 168_000_000


def test_engine_s21_310_subtraction(engine):
    """S21/310 = 311 + 312 - 313 (capital with loss deduction)."""
    data = {("S21", "311"): 60_000_000, ("S21", "312"): 25_000_000, ("S21", "313"): 0}
    result, _ = engine.apply(data)
    assert result[("S21", "310")] == 85_000_000


def test_engine_s21_310_with_loss(engine):
    data = {("S21", "311"): 10_000_000, ("S21", "312"): 0, ("S21", "313"): 2_000_000}
    result, _ = engine.apply(data)
    assert result[("S21", "310")] == 8_000_000


def test_engine_b7_household_total(engine):
    """B7/120 = 121 + 122 + 123 for each column."""
    data = {
        ("B7", "121/02"): 3_000_000,
        ("B7", "122/02"): 50_000_000,
        ("B7", "123/02"): 5_000_000,
    }
    result, _ = engine.apply(data)
    assert result[("B7", "120/02")] == 58_000_000


def test_engine_no_input_yields_no_output(engine):
    """If no relevant inputs provided, no derived fields should appear."""
    data = {}
    result, computed = engine.apply(data)
    assert result == {}
    assert computed == {}


def test_engine_does_not_override_user_input(engine):
    """User-supplied values are never overwritten by engine."""
    data = {("S11", "061"): 10_000_000, ("S11", "060"): 99_999_999}
    result, _ = engine.apply(data)
    # User supplied 060 → engine must not overwrite it
    assert result[("S11", "060")] == 99_999_999


def test_engine_conflict_detection(engine):
    """engine.check_conflicts should warn when user-supplied calc field differs."""
    user  = {("S11", "061"): 10_000_000, ("S11", "060"): 99_000_000}
    derived = dict(user)
    derived[("S11", "060")] = 10_000_000  # computed value

    warnings = engine.check_conflicts(user, derived)
    assert len(warnings) == 1
    assert "060" in warnings[0]


def test_engine_no_conflict_within_tolerance(engine):
    """Differences ≤ €500 (rounding noise) should not be flagged."""
    user    = {("S11", "061"): 10_000_200, ("S11", "060"): 10_000_000}
    derived = dict(user)
    derived[("S11", "060")] = 10_000_200

    warnings = engine.check_conflicts(user, derived)
    assert len(warnings) == 0


# ── csv_form_to_cat helper ────────────────────────────────────────────────────

def test_form_map_hv11():
    assert Catalogue.csv_form_to_cat("HV11") == "S11"


def test_form_map_hv22():
    assert Catalogue.csv_form_to_cat("HV22") == "S22"


def test_form_map_annex_passthrough():
    assert Catalogue.csv_form_to_cat("B7") == "B7"
    assert Catalogue.csv_form_to_cat("A1") == "A1"


# ── make_field_id helper ──────────────────────────────────────────────────────

def test_field_id_main_form():
    assert Catalogue.make_field_id("061", "00") == "061"


def test_field_id_annex():
    assert Catalogue.make_field_id("120", "02") == "120/02"


def test_field_id_zero_padding_preserved():
    assert Catalogue.make_field_id("010", "00") == "010"

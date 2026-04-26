"""
tests/test_catalogue.py — KreStA catalogue and engine unit tests.
Run from anywhere: pytest kresta/tests/test_catalogue.py
"""

import sys
from pathlib import Path
import pytest

PROJECT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT.parent))  # add bista/ so shared/ is importable
sys.path.insert(0, str(PROJECT))         # add kresta/ so local imports work

from shared.catalogue import Catalogue
from shared.engine import CalculationEngine

CATALOGUE_DIR = PROJECT


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def cat():
    return Catalogue(
        CATALOGUE_DIR,
        fields_file="kresta_fields.csv",
        calcs_file="kresta_calcs.csv",
        form_to_cat={},  # KreStA: identity mapping
    )


@pytest.fixture(scope="module")
def engine(cat):
    return CalculationEngine(cat)


# ── Catalogue loading ─────────────────────────────────────────────────────────

def test_fields_loaded(cat):
    assert len(cat.fields) > 0


def test_calcs_loaded(cat):
    assert len(cat.calcs) > 0


def test_v1_110_is_input(cat):
    assert cat.fields.get(("V1", "110")) == "input"


def test_v1_100_is_calculate(cat):
    assert cat.fields.get(("V1", "100")) == "calculate"


def test_v1_400_is_calculate(cat):
    assert cat.fields.get(("V1", "400")) == "calculate"


def test_v3_100_is_calculate(cat):
    assert cat.fields.get(("V3", "100")) == "calculate"


def test_v1_200_formula_present(cat):
    formula = cat.calcs.get(("V1", "200/01"))
    assert formula is not None
    assert "210/01" in formula
    assert "220/01" in formula
    assert "230/01" in formula


def test_v1_400_formula_present(cat):
    formula = cat.calcs.get(("V1", "400/01"))
    assert formula is not None
    assert "100/01" in formula
    assert "200/01" in formula
    assert "300/01" in formula


def test_v3_formula_uses_col05(cat):
    formula = cat.calcs.get(("V3", "100/05"))
    assert formula is not None
    assert "110/05" in formula


# ── Catalogue helpers ─────────────────────────────────────────────────────────

def test_form_passthrough(cat):
    """KreStA uses identity mapping — V1 stays V1."""
    assert cat.csv_form_to_cat("V1") == "V1"
    assert cat.csv_form_to_cat("V3") == "V3"
    assert cat.csv_form_to_cat("VA") == "VA"


def test_make_field_id_col01():
    assert Catalogue.make_field_id("110", "01") == "110/01"


def test_make_field_id_no_col():
    """col=00 → bare line (used internally, not in KreStA input CSVs)."""
    assert Catalogue.make_field_id("110", "00") == "110"


# ── Calculation engine ────────────────────────────────────────────────────────

def test_engine_v1_200_col01(engine):
    """V1/200/01 = 210/01 + 220/01 + 230/01."""
    data = {("V1", "210/01"): 5_000_000, ("V1", "220/01"): 10_000_000}
    result, _ = engine.apply(data)
    assert result[("V1", "200/01")] == 15_000_000


def test_engine_v1_100_col01(engine):
    """V1/100/01 = sum of sector rows."""
    data = {("V1", "130/01"): 50_000_000, ("V1", "180/01"): 20_000_000}
    result, _ = engine.apply(data)
    assert result[("V1", "100/01")] == 70_000_000


def test_engine_v1_400_chain(engine):
    """V1/400 resolves via 100 (which resolves from sectors) + 200 + 300."""
    data = {
        ("V1", "130/01"): 50_000_000,
        ("V1", "220/01"): 70_000_000,
    }
    result, _ = engine.apply(data)
    assert result[("V1", "100/01")] == 50_000_000
    assert result[("V1", "200/01")] == 70_000_000
    assert result[("V1", "400/01")] == 120_000_000


def test_engine_v3_col05(engine):
    """V3/100/05 = sum of sector rows for col 05."""
    data = {("V3", "130/05"): 80_000_000, ("V3", "140/05"): 20_000_000}
    result, _ = engine.apply(data)
    assert result[("V3", "100/05")] == 100_000_000


def test_engine_v3_col07_independent(engine):
    """V3/200/07 (mortgage totals) derived independently of col 05."""
    data = {("V3", "210/07"): 30_000_000, ("V3", "230/07"): 70_000_000}
    result, _ = engine.apply(data)
    assert result[("V3", "200/07")] == 100_000_000


def test_engine_no_input_yields_no_output(engine):
    result, computed = engine.apply({})
    assert result == {}
    assert computed == {}


def test_engine_user_input_not_overwritten(engine):
    """User-supplied totals are not overwritten by the engine."""
    data = {("V1", "220/01"): 50_000_000, ("V1", "200/01"): 99_000_000}
    result, _ = engine.apply(data)
    assert result[("V1", "200/01")] == 99_000_000

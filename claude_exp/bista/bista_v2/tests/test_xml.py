"""
tests/test_xml.py
Tests for XML output structure and content correctness.
Run from anywhere: pytest bista_v2/tests/test_xml.py
"""

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
import pytest

PROJECT  = Path(__file__).parent.parent
SCRIPT   = PROJECT / "annex_bista.py"
FIXTURES = Path(__file__).parent / "fixtures"
OUTPUT   = PROJECT / "output"
MELDER   = PROJECT / "config" / "melder.json"
PERIOD   = "2026-03"
NS       = "http://www.bundesbank.de/xmw/2003-01-01"

OUTPUT.mkdir(parents=True, exist_ok=True)


def run_script(input_csv, out_name, extra_args=None):
    """Run annex_bista.py and return (returncode, output_path, stdout, stderr)."""
    out_path = OUTPUT / out_name
    cmd = [
        sys.executable, str(SCRIPT),
        "--input",  str(input_csv),
        "--period", PERIOD,
        "--output", str(out_path),
        "--melder", str(MELDER),
        "--stufe",  "Test",
    ]
    if extra_args:
        cmd += extra_args
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, out_path, result.stdout, result.stderr


def get_field(root, pos):
    for feld in root.iter(f"{{{NS}}}FELD"):
        if feld.attrib.get("pos") == pos:
            return int(feld.text or 0)
    return None


def get_formular(root, name):
    for fm in root.iter(f"{{{NS}}}FORMULAR"):
        if fm.attrib.get("name") == name:
            return fm
    return None


# ── Infrastructure ────────────────────────────────────────────────────────────

def test_script_exists():
    assert SCRIPT.exists()


def test_melder_exists():
    assert MELDER.exists()


def test_minimal_fixture_exists():
    assert (FIXTURES / "minimal_input.csv").exists()


# ── Minimal run ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def minimal_xml():
    rc, out, stdout, stderr = run_script(FIXTURES / "minimal_input.csv",
                                         "test_minimal.xml")
    assert rc == 0, f"Script failed:\nstdout: {stdout}\nstderr: {stderr}"
    return ET.parse(str(out)).getroot()


def test_minimal_runs_clean(minimal_xml):
    assert minimal_xml is not None


def test_root_element(minimal_xml):
    tag = minimal_xml.tag
    assert "LIEFERUNG-BISTA" in tag


def test_stufe_test(minimal_xml):
    assert minimal_xml.attrib.get("stufe") == "Test"


def test_version(minimal_xml):
    assert minimal_xml.attrib.get("version") == "1.0"


def test_period_in_output(minimal_xml):
    termin = minimal_xml.find(f".//{{{NS}}}MELDETERMIN")
    assert termin is not None
    assert termin.text == PERIOD


def test_hv_formular_present(minimal_xml):
    assert get_formular(minimal_xml, "HV") is not None


def test_b7_formular_present(minimal_xml):
    assert get_formular(minimal_xml, "B7") is not None


def test_l1_formular_present(minimal_xml):
    assert get_formular(minimal_xml, "L1") is not None


# ── Position encoding ─────────────────────────────────────────────────────────

def test_hv11_020_encoding(minimal_xml):
    """HV11 line 020 → Z020S11."""
    val = get_field(minimal_xml, "Z020S11")
    assert val == 1_000  # 1,000,000 EUR → 1,000 Tsd


def test_hv11_071_encoding(minimal_xml):
    """HV11 line 071 → Z071S11."""
    val = get_field(minimal_xml, "Z071S11")
    assert val == 10_000  # 10,000,000 EUR → 10,000 Tsd


def test_hv21_210_encoding(minimal_xml):
    """HV21 line 210 → Z210S21."""
    val = get_field(minimal_xml, "Z210S21")
    assert val == 5_000


def test_b7_convenience_encoding(minimal_xml):
    """B7 line 122 col 02 → Z122S02."""
    val = get_field(minimal_xml, "Z122S02")
    assert val == 10_000


def test_l1_households_encoding(minimal_xml):
    """L1 line 220 col 01 → Z220S01."""
    val = get_field(minimal_xml, "Z220S01")
    assert val == 20_000


# ── Zero omission ─────────────────────────────────────────────────────────────

def test_revolving_absent_from_b7(minimal_xml):
    """B7 col 01 (revolving/overdrafts) was not supplied → must not appear in B7 formular."""
    b7 = get_formular(minimal_xml, "B7")
    assert b7 is not None
    revolving_in_b7 = [
        f for f in b7.iter(f"{{{NS}}}FELD")
        if f.attrib.get("pos", "").endswith("S01")
    ]
    assert len(revolving_in_b7) == 0, (
        f"Revolving credit fields found in B7: {[f.attrib['pos'] for f in revolving_in_b7]}"
    )


# ── Calculation engine in XML output ─────────────────────────────────────────

@pytest.fixture(scope="module")
def derived_xml():
    rc, out, stdout, stderr = run_script(FIXTURES / "calc_derivation.csv",
                                         "test_derived.xml")
    assert rc == 0, f"Script failed:\n{stderr}"
    return ET.parse(str(out)).getroot()


def test_s11_070_derived(derived_xml):
    """S11/070 not supplied → should be derived as S11/071 = 10,000,000."""
    val = get_field(derived_xml, "Z070S11")
    assert val == 10_000  # 10,000 Tsd


def test_s21_310_derived(derived_xml):
    """S21/310 = 311 + 312 - 313 = 8M + 3M - 0 = 11M."""
    val = get_field(derived_xml, "Z310S21")
    assert val == 11_000


# ── Full charge card example ──────────────────────────────────────────────────

@pytest.fixture(scope="module")
def full_xml():
    rc, out, stdout, stderr = run_script(FIXTURES / "full_cc_example.csv",
                                         "test_full_cc.xml")
    assert rc == 0, f"Script failed:\n{stderr}"
    return ET.parse(str(out)).getroot()


def test_full_hv11_061_encoded(full_xml):
    val = get_field(full_xml, "Z061S11")
    assert val == 40_000  # 40,000,000 → 40,000 Tsd


def test_full_b7_corporations_convenience(full_xml):
    val = get_field(full_xml, "Z114S02")
    assert val == 50_000


def test_full_b7_households_total_derived(full_xml):
    """B7/120/02 = 121/02 + 122/02 + 123/02 = 3M + 50M + 5M = 58M."""
    val = get_field(full_xml, "Z120S02")
    assert val == 58_000


def test_full_a1_bundesbank_col09(full_xml):
    """A1 line 114 col 09 (Bundesbank central bank balance) → Z114S09."""
    val = get_field(full_xml, "Z114S09")
    assert val == 2_000


def test_full_l1_domestic_households(full_xml):
    val = get_field(full_xml, "Z220S01")
    assert val == 110_000


def test_full_b3_formular_present(full_xml):
    assert get_formular(full_xml, "B3") is not None


def test_full_c1_formular_present(full_xml):
    assert get_formular(full_xml, "C1") is not None


# ── --no-catalogue flag ───────────────────────────────────────────────────────

def test_no_catalogue_flag():
    rc, out, stdout, stderr = run_script(
        FIXTURES / "minimal_input.csv",
        "test_no_cat.xml",
        extra_args=["--no-catalogue"]
    )
    assert rc == 0
    root = ET.parse(str(out)).getroot()
    assert get_formular(root, "HV") is not None


# ── Well-formed XML ───────────────────────────────────────────────────────────

def test_minimal_xml_is_well_formed():
    """Re-parse output to confirm it is valid XML."""
    rc, out, _, _ = run_script(FIXTURES / "minimal_input.csv", "test_wf.xml")
    assert rc == 0
    tree = ET.parse(str(out))   # raises if malformed
    assert tree is not None


# ── Reconciliation ────────────────────────────────────────────────────────────

def test_balance_sheet_reconciliation_full(full_xml):
    """HV11/180 (total assets) must equal HV21/330 (total liabilities) in Tsd."""
    assets = get_field(full_xml, "Z180S11")
    liabs  = get_field(full_xml, "Z330S21")
    if assets is None or liabs is None:
        pytest.skip("180 or 330 not derived — balance sheet items may be zero")
    assert assets == liabs, f"Balance sheet mismatch: assets={assets} liabs={liabs}"

"""
tests/test_xml.py — KreStA XML structure and encoding tests.
Run from anywhere: pytest kresta/tests/test_xml.py
"""

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
import pytest

PROJECT  = Path(__file__).parent.parent
SCRIPT   = PROJECT / "kresta.py"
FIXTURES = Path(__file__).parent / "fixtures"
OUTPUT   = PROJECT / "output"
MELDER   = PROJECT / "config" / "melder.json"
PERIOD   = "2026-03"
NS       = "http://www.bundesbank.de/xmw/2003-01-01"

OUTPUT.mkdir(parents=True, exist_ok=True)


def run_script(input_csv, out_name, extra_args=None):
    out_path = OUTPUT / out_name
    cmd = [
        sys.executable, str(SCRIPT),
        "--input",  str(input_csv),
        "--period", PERIOD,
        "--output", str(out_path),
        "--melder", str(MELDER),
    ]
    if extra_args:
        cmd.extend(extra_args)
    rc = subprocess.run(cmd, capture_output=True, text=True)
    return rc.returncode, out_path, rc.stdout, rc.stderr


def get_field(root, pos):
    for fm in root.iter(f"{{{NS}}}FORMULAR"):
        for f in fm.iter(f"{{{NS}}}FELD"):
            if f.attrib.get("pos") == pos:
                return int(f.text)
    return None


def get_formular(root, name):
    for fm in root.iter(f"{{{NS}}}FORMULAR"):
        if fm.attrib.get("name") == name:
            return fm
    return None


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def minimal_xml():
    rc, out, stdout, stderr = run_script(FIXTURES / "minimal_input.csv", "test_minimal.xml")
    assert rc == 0, f"Script failed:\nstdout: {stdout}\nstderr: {stderr}"
    return ET.parse(str(out)).getroot()


@pytest.fixture(scope="module")
def full_xml():
    rc, out, stdout, stderr = run_script(FIXTURES / "full_cc_example.csv", "test_full_cc.xml")
    assert rc == 0, f"Script failed:\nstdout: {stdout}\nstderr: {stderr}"
    return ET.parse(str(out)).getroot()


# ── Root element and envelope ─────────────────────────────────────────────────

def test_root_element(minimal_xml):
    assert minimal_xml.tag == f"{{{NS}}}LIEFERUNG-VJKRE"


def test_stufe_test(minimal_xml):
    assert minimal_xml.attrib.get("stufe") == "Test"


def test_version(minimal_xml):
    assert minimal_xml.attrib.get("version") == "1.0"


def test_period_in_output(minimal_xml):
    mt = minimal_xml.find(f".//{{{NS}}}MELDETERMIN")
    assert mt is not None and mt.text == PERIOD


def test_stufe_produktion():
    rc, out, _, _ = run_script(
        FIXTURES / "minimal_input.csv", "test_stufe_prod.xml",
        extra_args=["--stufe", "Produktion"]
    )
    assert rc == 0
    root = ET.parse(str(out)).getroot()
    assert root.attrib.get("stufe") == "Produktion"


# ── FORMULAR structure ────────────────────────────────────────────────────────

def test_v1_formular_present(minimal_xml):
    assert get_formular(minimal_xml, "V1") is not None


def test_no_hv_formular(minimal_xml):
    """KreStA must never produce an HV formular (that's BISTA-only)."""
    assert get_formular(minimal_xml, "HV") is None


def test_full_v2_formular_present(full_xml):
    assert get_formular(full_xml, "V2") is not None


def test_full_v1b_formular_present(full_xml):
    assert get_formular(full_xml, "V1B") is not None


def test_full_no_v3_formular(full_xml):
    """Pure charge card company has no long-term credit → V3 absent."""
    assert get_formular(full_xml, "V3") is None


# ── Position encoding ─────────────────────────────────────────────────────────

def test_v1_220_col01_encoding(minimal_xml):
    """V1/row 220/col 01 → Z220S01."""
    val = get_field(minimal_xml, "Z220S01")
    assert val == 120_000  # 120,000,000 EUR → 120,000 Tsd


def test_v1_200_derived(minimal_xml):
    """V1/200/01 derived from 220/01 (200 = 210+220+230)."""
    val = get_field(minimal_xml, "Z200S01")
    assert val == 120_000


def test_v1_400_derived(minimal_xml):
    """V1/400/01 derived from 100+200+300."""
    val = get_field(minimal_xml, "Z400S01")
    assert val == 120_000


def test_full_v1_100_derived(full_xml):
    """V1/100/01 = sum of enterprise sectors (130=50M)."""
    val = get_field(full_xml, "Z100S01")
    assert val == 50_000  # 50,000,000 EUR


def test_full_v1_400_grand_total(full_xml):
    """V1/400/01 = 100 (50M) + 200 (70M) + 300 (0) = 120M."""
    val = get_field(full_xml, "Z400S01")
    assert val == 120_000


# ── Zero omission ─────────────────────────────────────────────────────────────

def test_zero_rows_omitted(minimal_xml):
    """V1/110 was supplied as 0 in full example → must not appear."""
    val = get_field(minimal_xml, "Z110S01")
    assert val is None


# ── No-catalogue mode ─────────────────────────────────────────────────────────

def test_no_catalogue_mode():
    rc, out, _, _ = run_script(
        FIXTURES / "minimal_input.csv", "test_no_cat.xml",
        extra_args=["--no-catalogue"]
    )
    assert rc == 0
    root = ET.parse(str(out)).getroot()
    # Without catalogue, only user-supplied rows appear (no derived totals)
    assert get_field(root, "Z220S01") == 120_000
    assert get_field(root, "Z200S01") is None  # not derived
    assert get_field(root, "Z400S01") is None  # not derived


# ── Well-formed XML ───────────────────────────────────────────────────────────

def test_minimal_xml_is_well_formed():
    rc, out, _, _ = run_script(FIXTURES / "minimal_input.csv", "test_wf.xml")
    assert rc == 0
    tree = ET.parse(str(out))
    assert tree is not None

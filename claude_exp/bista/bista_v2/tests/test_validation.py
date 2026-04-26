"""
tests/test_validation.py
Tests for CLI validation, error handling, and reconciliation checks.
Run from anywhere: pytest bista_v2/tests/test_validation.py
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
NS       = "http://www.bundesbank.de/xmw/2003-01-01"

OUTPUT.mkdir(parents=True, exist_ok=True)


def run(input_csv, period="2026-03", out_name="test_validation.xml", extra=None):
    out_path = OUTPUT / out_name
    cmd = [
        sys.executable, str(SCRIPT),
        "--input",  str(input_csv),
        "--period", period,
        "--output", str(out_path),
        "--melder", str(MELDER),
    ]
    if extra:
        cmd += extra
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr, out_path


# ── Period format validation ──────────────────────────────────────────────────

def test_invalid_period_rejected():
    rc, _, stderr, _ = run(FIXTURES / "minimal_input.csv", period="03-2026",
                           out_name="test_bad_period.xml")
    assert rc != 0
    assert "period" in stderr.lower() or "YYYY-MM" in stderr


def test_period_wrong_format_dash():
    rc, _, _, _ = run(FIXTURES / "minimal_input.csv", period="2026/03",
                      out_name="test_bad_period2.xml")
    assert rc != 0


def test_valid_period_accepted():
    rc, _, _, _ = run(FIXTURES / "minimal_input.csv", period="2026-03",
                      out_name="test_valid_period.xml")
    assert rc == 0


# ── Missing file handling ─────────────────────────────────────────────────────

def test_missing_input_file_error():
    rc, _, stderr, _ = run(FIXTURES / "does_not_exist.csv",
                           out_name="test_missing.xml")
    assert rc != 0
    assert "not found" in stderr.lower() or "error" in stderr.lower()


def test_missing_melder_error():
    cmd = [
        sys.executable, str(SCRIPT),
        "--input",  str(FIXTURES / "minimal_input.csv"),
        "--period", "2026-03",
        "--output", str(OUTPUT / "test_bad_melder.xml"),
        "--melder", "/does/not/exist.json",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode != 0


# ── Unknown form warning (not an error) ──────────────────────────────────────

def test_unknown_form_produces_warning(tmp_path):
    csv = tmp_path / "unknown_form.csv"
    csv.write_text(
        "form,line,column,description,value_eur,comments\n"
        "XX99,100,01,Unknown form,1000000,\n",
        encoding="utf-8"
    )
    rc, _, stderr, _ = run(csv, out_name="test_unknown_form.xml")
    assert rc == 0  # unknown form is a warning, not an error
    assert "WARNING" in stderr and "XX99" in stderr


# ── Stufe choices ─────────────────────────────────────────────────────────────

def test_stufe_test_in_xml():
    rc, _, _, out = run(FIXTURES / "minimal_input.csv",
                        out_name="test_stufe_test.xml", extra=["--stufe", "Test"])
    assert rc == 0
    root = ET.parse(str(out)).getroot()
    assert root.attrib.get("stufe") == "Test"


def test_stufe_produktion_in_xml():
    rc, _, _, out = run(FIXTURES / "minimal_input.csv",
                        out_name="test_stufe_prod.xml", extra=["--stufe", "Produktion"])
    assert rc == 0
    root = ET.parse(str(out)).getroot()
    assert root.attrib.get("stufe") == "Produktion"


def test_invalid_stufe_rejected():
    rc, _, _, _ = run(FIXTURES / "minimal_input.csv",
                      out_name="test_bad_stufe.xml", extra=["--stufe", "Live"])
    assert rc != 0


# ── Reconciliation helper ─────────────────────────────────────────────────────

def get_field(root, pos):
    for feld in root.iter(f"{{{NS}}}FELD"):
        if feld.attrib.get("pos") == pos:
            return int(feld.text or 0)
    return None


def test_balance_mismatch_detected_by_reconciler():
    """
    Balance mismatch fixture: HV11/180 (10M) ≠ HV21/330 (9M).
    check_reconciliation.py should exit non-zero.
    """
    rc, _, _, out = run(FIXTURES / "balance_mismatch.csv",
                        out_name="test_balance_mismatch.xml")
    # Script itself succeeds (it just converts CSV to XML)
    assert rc == 0

    # Now run the reconciliation checker
    recon = PROJECT / "tests" / "check_reconciliation.py"
    result = subprocess.run(
        [sys.executable, str(recon), str(out)],
        capture_output=True, text=True
    )
    assert result.returncode != 0, "Reconciler should fail for mismatched balance sheet"


def test_balanced_sheet_passes_reconciler():
    """Minimal fixture has matching 180/330 after calculation."""
    rc, _, _, out = run(FIXTURES / "minimal_input.csv",
                        out_name="test_balanced.xml")
    assert rc == 0
    recon = PROJECT / "tests" / "check_reconciliation.py"
    result = subprocess.run(
        [sys.executable, str(recon), str(out)],
        capture_output=True, text=True
    )
    # May SKIP if fields not in XML (all zero), but must not FAIL
    assert result.returncode == 0, (
        f"Reconciler failed for balanced sheet:\n{result.stdout}\n{result.stderr}"
    )


# ── Calculated field conflict warning ────────────────────────────────────────

def test_conflict_warning_on_wrong_total(tmp_path):
    """User supplies HV11/060 = 5M but 061=10M 062=0 → computed 060=10M → warning."""
    csv = tmp_path / "conflict.csv"
    csv.write_text(
        "form,line,column,description,value_eur,comments\n"
        "HV11,061,00,Book claims on banks,10000000,\n"
        "HV11,060,00,Total loans to banks WRONG,5000000,Intentionally wrong\n"
        "HV21,311,00,Capital,10000000,\n",
        encoding="utf-8"
    )
    rc, _, stderr, _ = run(csv, out_name="test_conflict.xml")
    assert rc == 0  # mismatch is a warning not an error
    assert "WARNING" in stderr


# ── Empty CSV ─────────────────────────────────────────────────────────────────

def test_empty_csv_rejected(tmp_path):
    csv = tmp_path / "empty.csv"
    csv.write_text("form,line,column,description,value_eur,comments\n", encoding="utf-8")
    rc, _, stderr, _ = run(csv, out_name="test_empty.xml")
    assert rc != 0


def test_comments_only_csv_rejected(tmp_path):
    csv = tmp_path / "comments.csv"
    csv.write_text(
        "form,line,column,description,value_eur,comments\n"
        "# this is just a comment\n"
        "# another comment\n",
        encoding="utf-8"
    )
    rc, _, _, _ = run(csv, out_name="test_comments.xml")
    assert rc != 0

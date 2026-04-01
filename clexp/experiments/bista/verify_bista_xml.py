"""
verify_bista_xml.py — Validate a BISTA XMW XML file.

Two validation layers:
  1. XSD validation   — requires BbkXmwBsm.xsd (from Bundesbank ExtraNet).
                        Skipped with a warning if the file is not present.
  2. Structural checks — always run; verify namespace, required elements,
                         attribute values, position encoding, and amounts.

Usage:
    python3 verify_bista_xml.py bista2603.xml
    python3 verify_bista_xml.py bista2603.xml --xsd BbkXmwBsm.xsd
    python3 verify_bista_xml.py bista2412.xml --stufe Produktion
"""

import argparse
import re
import sys
from pathlib import Path

from lxml import etree

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BISTA_NS   = "http://www.bundesbank.de/xmw/2003-01-01"
BISTA_TAG  = f"{{{BISTA_NS}}}LIEFERUNG-BISTA"

VALID_STUFE  = {"Test", "Produktion"}
VALID_BEREICH = {"Statistik"}
VALID_MODUS  = {"Normal", "Korrektur", "Storno"}
VALID_NAME   = {"HV"}   # main form; annexes would extend this

# Z###S## or Z###_###S## (range positions like Z192_195S12)
POS_RE = re.compile(r"^Z\d{3}(_\d{3})?S\d{2}$")

MELDETERMIN_RE = re.compile(r"^\d{4}-\d{2}$")
DATETIME_RE    = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class Checker:
    def __init__(self):
        self.errors   = []
        self.warnings = []

    def error(self, msg):
        self.errors.append(f"  ERROR   {msg}")

    def warn(self, msg):
        self.warnings.append(f"  WARNING {msg}")

    def require(self, condition, msg):
        if not condition:
            self.error(msg)
        return condition

    def require_child(self, parent, tag, label=""):
        el = parent.find(tag)
        self.require(el is not None, f"<{label or tag}> missing")
        return el

    def require_text(self, el, label):
        if el is None:
            return None
        text = (el.text or "").strip()
        self.require(bool(text), f"<{label}> is empty")
        return text

    @property
    def ok(self):
        return len(self.errors) == 0


# ---------------------------------------------------------------------------
# Structural validation
# ---------------------------------------------------------------------------

def check_structure(root: etree._Element, c: Checker, expected_stufe: str | None) -> None:
    """Validate structure, attributes, and content of a LIEFERUNG-BISTA document."""

    # Root element
    c.require(root.tag == BISTA_TAG,
              f"Root element must be LIEFERUNG-BISTA in namespace {BISTA_NS}, got {root.tag!r}")

    # Root attributes
    stufe  = root.get("stufe", "")
    bereich = root.get("bereich", "")
    erstellzeit_root = root.get("erstellzeit", "")

    c.require(stufe in VALID_STUFE,
              f"stufe={stufe!r} not in {VALID_STUFE}")
    if expected_stufe:
        c.require(stufe == expected_stufe,
                  f"stufe={stufe!r} but expected {expected_stufe!r}")
    c.require(bereich in VALID_BEREICH,
              f"bereich={bereich!r} not in {VALID_BEREICH}")
    if erstellzeit_root:
        c.require(DATETIME_RE.match(erstellzeit_root),
                  f"Root erstellzeit={erstellzeit_root!r} not in YYYY-MM-DDTHH:MM:SS format")

    # ABSENDER (optional per spec, but warn if missing)
    absender = root.find(f"{{{BISTA_NS}}}ABSENDER")
    if absender is None:
        c.warn("ABSENDER element is missing (optional, but expected for ExtraNet submissions)")

    # MELDUNG
    meldung = c.require_child(root, f"{{{BISTA_NS}}}MELDUNG", "MELDUNG")
    if meldung is None:
        return  # can't continue without MELDUNG

    erstellzeit_m = meldung.get("erstellzeit", "")
    if erstellzeit_m:
        c.require(DATETIME_RE.match(erstellzeit_m),
                  f"MELDUNG erstellzeit={erstellzeit_m!r} not in YYYY-MM-DDTHH:MM:SS format")

    # MELDER
    melder = c.require_child(meldung, f"{{{BISTA_NS}}}MELDER", "MELDER")
    if melder is not None:
        blz  = melder.find(f"{{{BISTA_NS}}}BLZ")
        name = melder.find(f"{{{BISTA_NS}}}NAME")
        c.require(blz is not None and (blz.text or "").strip(),
                  "MELDER/BLZ is missing or empty")
        c.require(name is not None and (name.text or "").strip(),
                  "MELDER/NAME is missing or empty")
        land = melder.find(f"{{{BISTA_NS}}}LAND")
        if land is not None:
            c.require(len((land.text or "").strip()) == 2,
                      f"MELDER/LAND should be a 2-letter ISO country code, got {land.text!r}")

    # MELDETERMIN
    meldetermin_el = c.require_child(meldung, f"{{{BISTA_NS}}}MELDETERMIN", "MELDETERMIN")
    if meldetermin_el is not None:
        mt = (meldetermin_el.text or "").strip()
        c.require(MELDETERMIN_RE.match(mt),
                  f"MELDETERMIN={mt!r} must be YYYY-MM")

    # FORMULAR(s)
    formulare = meldung.findall(f"{{{BISTA_NS}}}FORMULAR")
    c.require(len(formulare) >= 1, "At least one FORMULAR element is required")

    for formular in formulare:
        name  = formular.get("name", "")
        modus = formular.get("modus", "")
        c.require(name in VALID_NAME,
                  f"FORMULAR name={name!r} not in {VALID_NAME}")
        c.require(modus in VALID_MODUS,
                  f"FORMULAR modus={modus!r} not in {VALID_MODUS}")

        felder = formular.findall(f"{{{BISTA_NS}}}FELD")
        if not felder:
            c.warn(f"FORMULAR name={name!r} has no FELD elements (void report?)")
            continue

        seen_pos = set()
        for feld in felder:
            pos = feld.get("pos", "")
            # Position format
            c.require(POS_RE.match(pos),
                      f"FELD pos={pos!r} does not match expected format Z###S## or Z###_###S##")
            # Duplicate positions
            if pos in seen_pos:
                c.error(f"Duplicate FELD pos={pos!r}")
            seen_pos.add(pos)
            # Amount must be a non-zero integer (spec: omit zeros)
            text = (feld.text or "").strip()
            c.require(bool(text), f"FELD pos={pos!r} has empty text")
            try:
                val = int(text)
                c.require(val != 0,
                          f"FELD pos={pos!r} is zero — zero positions should be omitted per spec")
            except ValueError:
                c.error(f"FELD pos={pos!r} value {text!r} is not an integer")


# ---------------------------------------------------------------------------
# XSD validation
# ---------------------------------------------------------------------------

def validate_xsd(xml_path: Path, xsd_path: Path, c: Checker) -> None:
    try:
        xsd_doc    = etree.parse(str(xsd_path))
        xsd_schema = etree.XMLSchema(xsd_doc)
        xml_doc    = etree.parse(str(xml_path))
        xsd_schema.validate(xml_doc)
        for err in xsd_schema.error_log:
            c.error(f"XSD line {err.line}: {err.message}")
    except etree.XMLSchemaParseError as e:
        c.error(f"Could not parse XSD: {e}")
    except etree.XMLSyntaxError as e:
        c.error(f"XML syntax error during XSD validation: {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a BISTA XMW XML file (structural + optional XSD).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 verify_bista_xml.py bista2603.xml\n"
            "  python3 verify_bista_xml.py bista2603.xml --xsd BbkXmwBsm.xsd\n"
            "  python3 verify_bista_xml.py bista2412.xml --stufe Produktion\n"
        ),
    )
    parser.add_argument("xml", help="BISTA XML file to validate")
    parser.add_argument("--xsd", default=None,
                        help="Path to BbkXmwBsm.xsd (from Bundesbank ExtraNet). "
                             "If omitted, structural checks only.")
    parser.add_argument("--stufe", choices=list(VALID_STUFE), default=None,
                        help="Assert that stufe matches this value (e.g. Produktion for live files).")
    args = parser.parse_args()

    xml_path = Path(args.xml)
    if not xml_path.exists():
        print(f"ERROR: File not found: {xml_path}", file=sys.stderr)
        sys.exit(1)

    c = Checker()
    print(f"Validating: {xml_path}")

    # --- Parse XML -----------------------------------------------------------
    try:
        tree = etree.parse(str(xml_path))
        root = tree.getroot()
    except etree.XMLSyntaxError as e:
        print(f"  ERROR   XML is not well-formed: {e}")
        sys.exit(1)

    # --- Structural checks ---------------------------------------------------
    print("  [1/2] Structural checks ...")
    check_structure(root, c, args.stufe)

    # --- XSD validation ------------------------------------------------------
    xsd_path = Path(args.xsd) if args.xsd else xml_path.parent / "BbkXmwBsm.xsd"
    print(f"  [2/2] XSD validation ({xsd_path.name}) ...")
    if xsd_path.exists():
        validate_xsd(xml_path, xsd_path, c)
    else:
        c.warn(f"XSD not found at {xsd_path} — skipping schema validation. "
               "Obtain BbkXmwBsm.xsd from Bundesbank ExtraNet and place it here.")

    # --- Report --------------------------------------------------------------
    print()
    if c.warnings:
        for w in c.warnings:
            print(w)
    if c.errors:
        for e in c.errors:
            print(e)
        print()
        print(f"FAIL — {len(c.errors)} error(s), {len(c.warnings)} warning(s).")
        sys.exit(1)
    else:
        print(f"OK — structural checks passed, {len(c.warnings)} warning(s).")
        sys.exit(0)


if __name__ == "__main__":
    main()

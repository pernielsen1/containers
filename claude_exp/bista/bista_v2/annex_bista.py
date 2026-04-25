#!/usr/bin/env python3
"""
annex_bista.py  —  BISTA v2: annex-level CSV → XMW XML

Usage:
    python3 annex_bista.py --input input/example.csv \
                           --period 2026-03 \
                           [--output output/bista_2026-03.xml] \
                           [--melder config/melder.json] \
                           [--stufe Test|Produktion]

CSV format (columns):  form, line, column, description, value_eur, comments
  - Lines starting with # and blank lines are ignored
  - form:   HV11 / HV12 / HV21 / HV22  (main form)  or  A1 / B1 / B7 / L1 … (annex)
  - line:   numeric row code within the form  (e.g. 071, 300)
  - column: 00 for single-value main-form items; 01-nn for annex columns
  - value_eur: full EUR amount; script converts to EUR thousands for XML

Position encoding:
  Main form  →  Z{line}S{subform}   e.g. HV11/071 → Z071S11
  Annexes    →  Z{line}S{column}    e.g. B7/300/01 → Z300S01

All HV11/HV12/HV21/HV22 items go into one <FORMULAR name="HV">.
Each annex gets its own <FORMULAR name="B7"> etc.
Zero values (after rounding to thousands) are omitted per XMW spec.
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path
import xml.etree.ElementTree as ET
from xml.dom import minidom

# ── Constants ─────────────────────────────────────────────────────────────────

XMW_NS      = "http://www.bundesbank.de/xmw/2003-01-01"
XMW_VERSION = "1.0"

HV_SUBFORMS = {"HV11": "11", "HV12": "12", "HV21": "21", "HV22": "22"}

ET.register_namespace("", XMW_NS)


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="BISTA annex-level CSV → Bundesbank XMW XML"
    )
    p.add_argument("--input",  required=True,  help="Input CSV file")
    p.add_argument("--period", required=True,  help="Reporting period YYYY-MM")
    p.add_argument("--output", default=None,   help="Output XML (default: output/bista_YYYY-MM.xml)")
    p.add_argument("--melder", default="config/melder.json", help="Melder config JSON")
    p.add_argument("--stufe",  default="Test", choices=["Test", "Produktion"])
    return p.parse_args()


# ── Loaders ───────────────────────────────────────────────────────────────────

def load_melder(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_csv(path):
    """
    Returns list of (form, line_str, col_str, value_int).
    Skips blank lines and comment lines starting with #.
    """
    data_lines = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for raw in f:
            s = raw.strip()
            if s and not s.startswith("#"):
                data_lines.append(raw)

    if not data_lines:
        return []

    rows = []
    reader = csv.DictReader(data_lines)
    for row in reader:
        form = row.get("form", "").strip()
        if not form:
            continue
        try:
            value = int(float(row["value_eur"].strip()))
        except (ValueError, KeyError):
            continue
        line_s = row["line"].strip().zfill(3)
        col_s  = row["column"].strip().zfill(2)
        rows.append((form, line_s, col_s, value))
    return rows


# ── Encoding ──────────────────────────────────────────────────────────────────

def encode_pos(form, line, col):
    """
    Z{line}S{subform}  for HV11/12/21/22   →  Z071S11
    Z{line}S{col}      for all annexes      →  Z300S01
    """
    if form in HV_SUBFORMS:
        return f"Z{line}S{HV_SUBFORMS[form]}"
    return f"Z{line}S{col}"


def build_formulars(rows):
    """
    Group rows into {formular_name: [(pos, value_tsd), ...]}.
    HV11/12/21/22 merge into 'HV'.  Each annex is separate.
    Zero values after EUR→thousands rounding are dropped.
    Output order: HV first, then annexes alphabetically.
    """
    bucket = {}
    for form, line, col, value_eur in rows:
        value_tsd = round(value_eur / 1000)
        if value_tsd == 0:
            continue
        pos  = encode_pos(form, line, col)
        name = "HV" if form in HV_SUBFORMS else form
        bucket.setdefault(name, []).append((pos, value_tsd))

    ordered = {}
    if "HV" in bucket:
        ordered["HV"] = bucket.pop("HV")
    for k in sorted(bucket):
        ordered[k] = bucket[k]
    return ordered


# ── XML builder ───────────────────────────────────────────────────────────────

def _t(name):
    return f"{{{XMW_NS}}}{name}"


def build_xml(melder, period, stufe, formulars):
    root = ET.Element(_t("LIEFERUNG-BISTA"))
    root.set("version", XMW_VERSION)
    root.set("stufe",   stufe)
    root.set("bereich", "Statistik")

    # ABSENDER (data centre)
    ab = ET.SubElement(root, _t("ABSENDER"))
    ET.SubElement(ab, _t("RZLZ")).text = melder["rzlz"]
    ET.SubElement(ab, _t("NAME")).text = melder["absender_name"]

    # MELDUNG
    ml = ET.SubElement(root, _t("MELDUNG"))

    # MELDER (reporting institution)
    me = ET.SubElement(ml, _t("MELDER"))
    ET.SubElement(me, _t("BLZ")).text    = melder["blz"]
    ET.SubElement(me, _t("NAME")).text   = melder["melder_name"]
    ET.SubElement(me, _t("STRASSE")).text = melder["strasse"]
    ET.SubElement(me, _t("PLZ")).text    = melder["plz"]
    ET.SubElement(me, _t("ORT")).text    = melder["ort"]
    ko = ET.SubElement(me, _t("KONTAKT"))
    ET.SubElement(ko, _t("NAME")).text    = melder["kontakt"]
    ET.SubElement(ko, _t("TELEFON")).text = melder["telefon"]
    ET.SubElement(ko, _t("EMAIL")).text   = melder["email"]

    ET.SubElement(ml, _t("MELDETERMIN")).text = period

    for fname, fields in formulars.items():
        fm = ET.SubElement(ml, _t("FORMULAR"))
        fm.set("name",  fname)
        fm.set("modus", "Normal")
        for pos, value_tsd in fields:
            fd = ET.SubElement(fm, _t("FELD"))
            fd.set("pos", pos)
            fd.text = str(value_tsd)

    return root


def to_pretty_xml(root):
    raw = ET.tostring(root, encoding="unicode", xml_declaration=False)
    dom = minidom.parseString(raw)
    return dom.toprettyxml(indent="  ", encoding="UTF-8").decode("utf-8")


# ── Validation ────────────────────────────────────────────────────────────────

def validate_period(period):
    if not re.fullmatch(r"\d{4}-\d{2}", period):
        print(f"ERROR: --period must be YYYY-MM, got: {period}", file=sys.stderr)
        sys.exit(1)


def warn_unknown_forms(rows):
    known = set(HV_SUBFORMS) | {
        "A1","A2","A3",
        "B1","B3","B4","B6","B7","BA",
        "C1","C2","C3","C4","C5",
        "D1","D2",
        "E1","E2","E3","E4","E5",
        "F1","F2",
        "H1","H2",
        "I1","I2",
        "L1","L2",
        "M1","M2",
        "O1","O2","P1","Q1","S1",
    }
    seen = {form for form, *_ in rows}
    unknown = seen - known
    for u in sorted(unknown):
        print(f"WARNING: unknown form '{u}' — included as-is", file=sys.stderr)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    validate_period(args.period)

    melder = load_melder(args.melder)
    rows   = load_csv(args.input)

    if not rows:
        print("ERROR: no data rows found in input CSV", file=sys.stderr)
        sys.exit(1)

    warn_unknown_forms(rows)

    formulars = build_formulars(rows)
    xml_root  = build_xml(melder, args.period, args.stufe, formulars)
    xml_str   = to_pretty_xml(xml_root)

    out_path = Path(args.output) if args.output \
               else Path("output") / f"bista_{args.period}.xml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(xml_str, encoding="utf-8")

    # Summary
    total_fields = sum(len(v) for v in formulars.values())
    print(f"Written : {out_path}")
    print(f"Period  : {args.period}  |  Stufe: {args.stufe}")
    print(f"Forms   : {', '.join(formulars)}")
    print(f"Fields  : {total_fields}")


if __name__ == "__main__":
    main()

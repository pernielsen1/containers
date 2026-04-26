#!/usr/bin/env python3
"""
annex_bista.py  —  BISTA v2: annex-level CSV → XMW XML

Usage:
    python3 annex_bista.py --input input/example.csv --period 2026-03
    python3 annex_bista.py --input input/example.csv --period 2026-03 --stufe Produktion
    python3 annex_bista.py --input input/example.csv --period 2026-03 --no-catalogue

CSV format (columns):  form, line, column, description, value_eur, comments
  - Lines starting with # and blank lines are ignored
  - form:   HV11 / HV12 / HV21 / HV22  or  A1 / B1 / B7 / L1 … (annex code)
  - line:   numeric row code from official Bundesbank form template
  - column: 00 for single-value main-form items; 01-nn for annex matrix columns
  - value_eur: full EUR amount (script converts to EUR thousands for XML)

Position encoding:
  HV11/12/21/22 →  Z{line}S{subform}   e.g. HV11/071 → Z071S11
  Annexes       →  Z{line}S{column}    e.g. B7/120/02 → Z120S02

All HV11/HV12/HV21/HV22 items go into one <FORMULAR name="HV">.
Each annex gets its own <FORMULAR name="B7"> etc.
Zero values (after EUR→thousands rounding) are omitted per XMW spec.

Catalogue:
  bista_fields.csv and bista_calcs.csv (in script directory by default) drive
  automatic derivation of calculated fields and field-method validation.
  Use --no-catalogue to skip catalogue loading.
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

# Input CSV form names → XML subform suffix
HV_SUBFORMS = {"HV11": "11", "HV12": "12", "HV21": "21", "HV22": "22"}

# Input CSV form names → catalogue form key (S11 etc.)
FORM_TO_CAT = {"HV11": "S11", "HV12": "S12", "HV21": "S21", "HV22": "S22"}

ET.register_namespace("", XMW_NS)


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="BISTA annex-level CSV → Bundesbank XMW XML"
    )
    p.add_argument("--input",  required=True,  help="Input CSV file")
    p.add_argument("--period", required=True,  help="Reporting period YYYY-MM")
    p.add_argument("--output", default=None,   help="Output XML (default: output/bista_YYYY-MM.xml)")
    p.add_argument("--melder", default=None,   help="Melder config JSON (default: config/melder.json next to script)")
    p.add_argument("--stufe",  default="Test", choices=["Test", "Produktion"])
    p.add_argument("--no-catalogue", action="store_true",
                   help="Skip catalogue loading and calculation engine")
    p.add_argument("--catalogue-dir", default=None,
                   help="Directory containing bista_fields.csv / bista_calcs.csv (default: script dir)")
    return p.parse_args()


# ── Catalogue ─────────────────────────────────────────────────────────────────

class Catalogue:
    """
    Loads bista_fields.csv and bista_calcs.csv.

    Fields CSV: form;field_id;description_en;method;relevant_charge_card;notes
      method = input | calculate | sub | nil
    Calcs CSV:  form;field_id;formula
      formula = simple arithmetic like "061 + 062" or "110/01 + 120/01"
    """

    def __init__(self, catalogue_dir):
        self.fields = {}   # (cat_form, field_id) → method
        self.calcs  = {}   # (cat_form, field_id) → formula str
        self._load(Path(catalogue_dir))

    def _load(self, d):
        fp = d / "bista_fields.csv"
        cp = d / "bista_calcs.csv"
        if fp.exists():
            with open(fp, encoding="utf-8-sig") as f:
                for row in csv.DictReader(f, delimiter=";"):
                    self.fields[(row["form"], row["field_id"])] = row["method"]
        else:
            print(f"NOTE: catalogue fields not found at {fp} — running without field validation",
                  file=sys.stderr)
        if cp.exists():
            with open(cp, encoding="utf-8-sig") as f:
                for row in csv.DictReader(f, delimiter=";"):
                    self.calcs[(row["form"], row["field_id"])] = row["formula"]
        else:
            print(f"NOTE: catalogue calcs not found at {cp} — running without auto-calculation",
                  file=sys.stderr)

    @staticmethod
    def csv_form_to_cat(csv_form):
        return FORM_TO_CAT.get(csv_form, csv_form)

    @staticmethod
    def make_field_id(line, col):
        """Convert (line, col) from input CSV to catalogue field_id."""
        if col == "00":
            return line          # main-form items: just the line e.g. "061"
        return f"{line}/{col}"   # annex items: "row/col" e.g. "120/02"

    def method_of(self, csv_form, line, col):
        cat_form = self.csv_form_to_cat(csv_form)
        fid      = self.make_field_id(line, col)
        return self.fields.get((cat_form, fid), "input")

    def is_empty(self):
        return not self.fields and not self.calcs


# ── Calculation engine ────────────────────────────────────────────────────────

class CalculationEngine:
    """
    Derives calculated fields from input data using bista_calcs.csv formulas.

    Data format: {(cat_form, field_id): value_eur_int}
    """

    def __init__(self, catalogue):
        self.catalogue = catalogue

    def apply(self, data):
        """
        Returns (merged, computed) where:
          merged   = user data + all derivable calculated values
                     (user-supplied values take precedence over computed ones)
          computed = dict of values the engine derived independently from inputs,
                     regardless of what the user supplied for those fields
        Iterates up to 5 passes to resolve dependency chains.
        """
        result   = dict(data)
        computed = {}

        for _ in range(5):
            changed = False
            for (cat_form, field_id), formula in self.catalogue.calcs.items():
                val = self._eval(cat_form, field_id, formula, result)
                if val is None:
                    continue
                computed[(cat_form, field_id)] = val   # always track computed
                if (cat_form, field_id) not in result:  # user-supplied takes precedence
                    result[(cat_form, field_id)] = val
                    changed = True
            if not changed:
                break
        return result, computed

    def check_conflicts(self, user_data, computed):
        """
        Warn when a user-supplied field marked 'calculate' in the catalogue
        differs from the independently computed value by more than €500.
        Returns list of warning strings.
        """
        warnings = []
        for (cat_form, fid), user_val in user_data.items():
            if self.catalogue.fields.get((cat_form, fid)) != "calculate":
                continue
            engine_val = computed.get((cat_form, fid))
            if engine_val is None:
                continue
            if abs(user_val - engine_val) > 500:
                warnings.append(
                    f"  {cat_form}/{fid}: you supplied {user_val:,} "
                    f"but engine computed {engine_val:,} — check inputs"
                )
        return warnings

    def _eval(self, cat_form, target_fid, formula, data):
        """
        Parse and evaluate a formula string.  Tokens are field_ids in the same
        form.  If a bare row token (e.g. '210') is used in a formula for a
        target that has a column suffix (e.g. '260/03'), the column is inherited
        automatically.
        """
        # Determine column to inherit (for annex row/col formulas)
        col_suffix = None
        if "/" in target_fid:
            col_suffix = target_fid.split("/")[1]

        tokens = re.findall(r'[+\-]|[^\s+\-]+', formula.replace(" ", ""))
        sign = 1
        total = 0
        any_found = False

        for token in tokens:
            if token == "+":
                sign = 1
            elif token == "-":
                sign = -1
            else:
                fid = token
                # Try inherited column if token has no "/"
                if col_suffix and "/" not in fid:
                    fid_with_col = f"{fid}/{col_suffix}"
                    val = data.get((cat_form, fid_with_col), data.get((cat_form, fid)))
                else:
                    val = data.get((cat_form, fid))

                if val is not None:
                    total += sign * val
                    any_found = True
                sign = 1

        return total if any_found else None


# ── Data loading and conversion ───────────────────────────────────────────────

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


def rows_to_data(rows):
    """Convert list of (form, line, col, value) to {(cat_form, field_id): value}."""
    data = {}
    for form, line, col, value in rows:
        cat_form = Catalogue.csv_form_to_cat(form)
        fid      = Catalogue.make_field_id(line, col)
        data[(cat_form, fid)] = value
    return data


def data_to_rows(data):
    """Convert {(cat_form, field_id): value} back to [(form, line, col, value)]."""
    result = []
    CAT_TO_FORM = {v: k for k, v in FORM_TO_CAT.items()}
    for (cat_form, fid), value in data.items():
        csv_form = CAT_TO_FORM.get(cat_form, cat_form)
        if "/" in fid:
            line, col = fid.split("/", 1)
        else:
            line, col = fid, "00"
        result.append((csv_form, line.zfill(3), col.zfill(2), value))
    return result


# ── Encoding ──────────────────────────────────────────────────────────────────

def encode_pos(form, line, col):
    """
    Z{line}S{subform}  for HV11/12/21/22   →  Z071S11
    Z{line}S{col}      for all annexes      →  Z120S02
    """
    if form in HV_SUBFORMS:
        return f"Z{line}S{HV_SUBFORMS[form]}"
    return f"Z{line}S{col}"


def build_formulars(rows):
    """
    Group rows into {formular_name: [(pos, value_tsd), ...]}.
    HV11/12/21/22 merge into 'HV'.  Each annex is separate.
    Zero values after EUR→thousands rounding are dropped.
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

    ab = ET.SubElement(root, _t("ABSENDER"))
    ET.SubElement(ab, _t("RZLZ")).text = melder["rzlz"]
    ET.SubElement(ab, _t("NAME")).text = melder["absender_name"]

    ml = ET.SubElement(root, _t("MELDUNG"))

    me = ET.SubElement(ml, _t("MELDER"))
    ET.SubElement(me, _t("BLZ")).text     = melder["blz"]
    ET.SubElement(me, _t("NAME")).text    = melder["melder_name"]
    ET.SubElement(me, _t("STRASSE")).text = melder["strasse"]
    ET.SubElement(me, _t("PLZ")).text     = melder["plz"]
    ET.SubElement(me, _t("ORT")).text     = melder["ort"]
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

KNOWN_FORMS = set(HV_SUBFORMS) | {
    "A1","A2","A3",
    "B1","B3","B4","B6","B7","BA",
    "C1","C2","C3","C4","C5",
    "D1","D2",
    "E1","E2","E3","E4","E5",
    "F1","F2",
    "H",
    "I1","I2",
    "L1","L2",
    "M1","M2",
    "O1","O2","P1","Q1","S1",
}


def validate_period(period):
    if not re.fullmatch(r"\d{4}-\d{2}", period):
        print(f"ERROR: --period must be YYYY-MM, got: {period}", file=sys.stderr)
        sys.exit(1)


def warn_unknown_forms(rows):
    seen = {form for form, *_ in rows}
    for u in sorted(seen - KNOWN_FORMS):
        print(f"WARNING: unknown form '{u}' — included as-is in XML", file=sys.stderr)


def validate_methods(rows, catalogue):
    """Warn about fields marked 'nil' in catalogue but supplied with a value."""
    for form, line, col, value in rows:
        method = catalogue.method_of(form, line, col)
        if method == "nil" and value != 0:
            fid = Catalogue.make_field_id(line, col)
            cat_form = Catalogue.csv_form_to_cat(form)
            print(f"WARNING: {cat_form}/{fid} is marked nil in catalogue "
                  f"but value {value:,} was supplied", file=sys.stderr)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    validate_period(args.period)

    # Resolve melder config
    melder_path = Path(args.melder) if args.melder \
                  else Path(__file__).parent / "config" / "melder.json"
    if not melder_path.exists():
        print(f"ERROR: melder config not found: {melder_path}", file=sys.stderr)
        sys.exit(1)
    melder = load_melder(melder_path)

    # Load input CSV
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    rows = load_csv(input_path)
    if not rows:
        print("ERROR: no data rows found in input CSV", file=sys.stderr)
        sys.exit(1)

    warn_unknown_forms(rows)

    # Catalogue + calculation engine
    if not args.no_catalogue:
        cat_dir = Path(args.catalogue_dir) if args.catalogue_dir \
                  else Path(__file__).parent
        catalogue = Catalogue(cat_dir)

        if not catalogue.is_empty():
            validate_methods(rows, catalogue)

            # Convert to dict, apply calculations, convert back
            user_data       = rows_to_data(rows)
            engine          = CalculationEngine(catalogue)
            merged, computed = engine.apply(user_data)

            conflicts = engine.check_conflicts(user_data, computed)
            for w in conflicts:
                print(f"WARNING: calculated-field mismatch:\n{w}", file=sys.stderr)

            rows = data_to_rows(merged)

    # Build and write XML
    formulars = build_formulars(rows)
    xml_root  = build_xml(melder, args.period, args.stufe, formulars)
    xml_str   = to_pretty_xml(xml_root)

    out_path = Path(args.output) if args.output \
               else Path(__file__).parent / "output" / f"bista_{args.period}.xml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(xml_str, encoding="utf-8")

    total_fields = sum(len(v) for v in formulars.values())
    print(f"Written : {out_path}")
    print(f"Period  : {args.period}  |  Stufe: {args.stufe}")
    print(f"Forms   : {', '.join(formulars)}")
    print(f"Fields  : {total_fields}")


if __name__ == "__main__":
    main()

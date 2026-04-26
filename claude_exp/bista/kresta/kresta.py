#!/usr/bin/env python3
"""
kresta.py  —  KreStA: quarterly borrower statistics (Kreditnehmerstatistik) CSV → XMW XML

Usage:
    python3 kresta.py --input input/example.csv --period 2026-03
    python3 kresta.py --input input/example.csv --period 2026-03 --stufe Produktion
    python3 kresta.py --input input/example.csv --period 2026-03 --no-catalogue

CSV format (columns):  form, line, column, description, value_eur, comments
  - Lines starting with # and blank lines are ignored
  - form:   V1 / V2 / V3 / V4 / VA / VB  (main forms)
            V1B / V2B / V3B / V4B / VAB / VBB  (value-adjustment forms)
  - line:   numeric row code (100, 110, 120 … 400)
  - column: credit type column
              V1/V2/VA/VAB: 01=Forderungen≤1yr  02=Forderungen>1yr≤5yr
                            03=Wechseldiskontkredite  04=Wechsel im Bestand
              V3/V4/VB/V3B: 05=Forderungen>5yr(ohne Hyp)  06=Treuhand(deprecated=nil)
                            07=Hypothekarkredite insgesamt  08=Hyp auf Wohngrundstücke
  - value_eur: full EUR amount (script converts to EUR thousands for XML)

Position encoding (same as BISTA annexes):
  Z{line}S{col}    e.g. V1/110/01 → Z110S01,  V3/200/07 → Z200S07

Each form gets its own <FORMULAR name="V1"> etc. No HV-style merging.

Catalogue:
  kresta_fields.csv and kresta_calcs.csv (in script directory by default) drive
  automatic derivation of calculated totals (rows 100, 200, 400).
  Use --no-catalogue to skip.

Period:
  Use the last month of the quarter in YYYY-MM format:
    Q1 → 2026-03   Q2 → 2026-06   Q3 → 2026-09   Q4 → 2026-12

Reconciliation:
  V1/Z400 + V3/Z400 (all columns summed) must equal BISTA B1/Z100 (total
  loans to domestic enterprises and households).
"""

import argparse
import re
import sys
from pathlib import Path

# Add bista/ parent to path so shared/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.xmw import load_melder, build_formulars, build_xml, to_pretty_xml
from shared.catalogue import Catalogue
from shared.engine import CalculationEngine
from shared.csv_io import load_csv, rows_to_data, data_to_rows

# ── KreStA-specific constants ─────────────────────────────────────────────────

# No HV-form merging for KreStA — each form keeps its own FORMULAR
HV_SUBFORMS = {}
# No catalogue key remapping — V1 stays V1, V3 stays V3
FORM_TO_CAT = {}

KNOWN_FORMS = {
    "V1", "V2", "V3", "V4", "VA", "VB",
    "V1B", "V2B", "V3B", "V4B", "VAB", "VBB",
}

# Column S06 (Treuhandkredite) is deprecated since 2021 — report nil
DEPRECATED_COLS = {("V3", "06"), ("V4", "06"), ("VB", "06"),
                   ("V3B", "06"), ("V4B", "06"), ("VBB", "06")}


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="KreStA quarterly borrower statistics CSV → Bundesbank XMW XML"
    )
    p.add_argument("--input",  required=True,  help="Input CSV file")
    p.add_argument("--period", required=True,  help="Reporting period YYYY-MM (last month of quarter)")
    p.add_argument("--output", default=None,   help="Output XML (default: output/kresta_YYYY-MM.xml)")
    p.add_argument("--melder", default=None,   help="Melder config JSON (default: config/melder.json next to script)")
    p.add_argument("--stufe",  default="Test", choices=["Test", "Produktion"])
    p.add_argument("--no-catalogue", action="store_true",
                   help="Skip catalogue loading and calculation engine")
    p.add_argument("--catalogue-dir", default=None,
                   help="Directory containing kresta_fields.csv / kresta_calcs.csv (default: script dir)")
    return p.parse_args()


# ── Validation ────────────────────────────────────────────────────────────────

def validate_period(period):
    if not re.fullmatch(r"\d{4}-\d{2}", period):
        print(f"ERROR: --period must be YYYY-MM, got: {period}", file=sys.stderr)
        sys.exit(1)
    month = int(period.split("-")[1])
    if month not in (3, 6, 9, 12):
        print(f"WARNING: period month {month:02d} is not a quarter-end — "
              f"expected 03, 06, 09, or 12", file=sys.stderr)


def warn_unknown_forms(rows):
    seen = {form for form, *_ in rows}
    for u in sorted(seen - KNOWN_FORMS):
        print(f"WARNING: unknown form '{u}' — included as-is in XML", file=sys.stderr)


def warn_deprecated_cols(rows):
    for form, line, col, value in rows:
        if (form, col) in DEPRECATED_COLS and value != 0:
            print(f"WARNING: {form}/Z{line}S{col} (Treuhandkredite) is deprecated "
                  f"since 2021 — should be zero", file=sys.stderr)


def validate_methods(rows, catalogue):
    for form, line, col, value in rows:
        method = catalogue.method_of(form, line, col)
        if method == "nil" and value != 0:
            fid = Catalogue.make_field_id(line, col)
            print(f"WARNING: {form}/{fid} is marked nil in catalogue "
                  f"but value {value:,} was supplied", file=sys.stderr)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    validate_period(args.period)

    melder_path = Path(args.melder) if args.melder \
                  else Path(__file__).parent / "config" / "melder.json"
    if not melder_path.exists():
        print(f"ERROR: melder config not found: {melder_path}", file=sys.stderr)
        sys.exit(1)
    melder = load_melder(melder_path)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    rows = load_csv(input_path)
    if not rows:
        print("ERROR: no data rows found in input CSV", file=sys.stderr)
        sys.exit(1)

    warn_unknown_forms(rows)
    warn_deprecated_cols(rows)

    if not args.no_catalogue:
        cat_dir = Path(args.catalogue_dir) if args.catalogue_dir \
                  else Path(__file__).parent
        catalogue = Catalogue(
            cat_dir,
            fields_file="kresta_fields.csv",
            calcs_file="kresta_calcs.csv",
            form_to_cat=FORM_TO_CAT,
        )

        if not catalogue.is_empty():
            validate_methods(rows, catalogue)

            user_data        = rows_to_data(rows, catalogue)
            engine           = CalculationEngine(catalogue)
            merged, computed = engine.apply(user_data)

            conflicts = engine.check_conflicts(user_data, computed)
            for w in conflicts:
                print(f"WARNING: calculated-field mismatch:\n{w}", file=sys.stderr)

            rows = data_to_rows(merged, catalogue)

    # KreStA: no HV merging, each form its own FORMULAR
    formulars = build_formulars(rows, hv_subforms=None)
    xml_root  = build_xml(melder, args.period, args.stufe, formulars,
                          root_element="LIEFERUNG-VJKRE")
    xml_str   = to_pretty_xml(xml_root)

    out_path = Path(args.output) if args.output \
               else Path(__file__).parent / "output" / f"kresta_{args.period}.xml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(xml_str, encoding="utf-8")

    total_fields = sum(len(v) for v in formulars.values())
    print(f"Written : {out_path}")
    print(f"Period  : {args.period}  |  Stufe: {args.stufe}")
    print(f"Forms   : {', '.join(formulars)}")
    print(f"Fields  : {total_fields}")


if __name__ == "__main__":
    main()

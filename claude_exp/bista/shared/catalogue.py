"""
shared/catalogue.py — Field catalogue and method loader, shared by BISTA and KreStA.

The fields CSV columns: form;field_id;description_en;method;...
  method = input | calculate | sub | nil
The calcs CSV columns:  form;field_id;formula
  formula = simple arithmetic like "061 + 062" or "110/01 + 120/01"

form_to_cat maps input CSV form names to catalogue form keys:
  BISTA: {"HV11": "S11", "HV12": "S12", "HV21": "S21", "HV22": "S22"}
  KreStA: {} or None  (identity — V1 stays V1, etc.)
"""

import csv
import sys
from pathlib import Path


class Catalogue:
    def __init__(self, catalogue_dir, fields_file="bista_fields.csv",
                 calcs_file="bista_calcs.csv", form_to_cat=None):
        self._form_to_cat = form_to_cat or {}
        self.fields = {}   # (cat_form, field_id) → method
        self.calcs  = {}   # (cat_form, field_id) → formula str
        self._load(Path(catalogue_dir), fields_file, calcs_file)

    def _load(self, d, fields_file, calcs_file):
        fp = d / fields_file
        cp = d / calcs_file
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

    def csv_form_to_cat(self, csv_form):
        """Translate a CSV input form name to the catalogue's internal key."""
        return self._form_to_cat.get(csv_form, csv_form)

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

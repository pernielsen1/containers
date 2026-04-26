"""
shared/csv_io.py — CSV loading and row↔dict conversion, shared by BISTA and KreStA.

Input CSV format (semicolon-free, comma-separated):
  form,line,column,description,value_eur,comments
  Lines starting with # and blank lines are ignored.
"""

import csv


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


def rows_to_data(rows, catalogue):
    """Convert list of (form, line, col, value) to {(cat_form, field_id): value}."""
    data = {}
    for form, line, col, value in rows:
        cat_form = catalogue.csv_form_to_cat(form)
        fid      = catalogue.make_field_id(line, col)
        data[(cat_form, fid)] = value
    return data


def data_to_rows(data, catalogue):
    """Convert {(cat_form, field_id): value} back to [(form, line, col, value)]."""
    cat_to_form = {v: k for k, v in catalogue._form_to_cat.items()}
    result = []
    for (cat_form, fid), value in data.items():
        csv_form = cat_to_form.get(cat_form, cat_form)
        if "/" in fid:
            line, col = fid.split("/", 1)
        else:
            line, col = fid, "00"
        result.append((csv_form, line.zfill(3), col.zfill(2), value))
    return result

#!/usr/bin/env python3
"""
load_new_counterparties.py — Validate new counterparty records before loading.

Reads new_counterparties.csv and checks each record against the existing
counterparties.csv.  Produces two output files:

  OK_new_counterparties.csv  — records with no possible duplicate found
  possible_errors.csv        — one row per (new record, matching existing record) pair

possible_errors.csv column order:
  <all columns from new record>  |  <all columns from existing record, prefixed exist_>  |  overall_score

Usage:
  python3 load_new_counterparties.py <new_counterparties.csv> [options]

Options:
  --existing       Path to existing counterparties CSV  (default: counterparties.csv)
  --ok-output      Path for OK records                  (default: OK_new_counterparties.csv)
  --errors-output  Path for possible errors             (default: possible_errors.csv)
  --method         trigram | canonical                  (default: canonical)
  --threshold      Overall score 0–1                    (default: 0.70)
  --ignore         Path to ignore.csv                   (default: ignore.csv)
"""

import argparse
import sys

from duplicate_utils import (
    REQUIRED_COLS, COL_ID,
    read_csv, write_csv,
    find_cross_pairs, load_ignore,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check new counterparty records for possible duplicates against an existing file."
    )
    parser.add_argument("input", help="New counterparties CSV (semicolon-delimited, utf-8-sig)")
    parser.add_argument("--existing",       default="counterparties.csv")
    parser.add_argument("--ok-output",      default="OK_new_counterparties.csv")
    parser.add_argument("--errors-output",  default="possible_errors.csv")
    parser.add_argument("--method",         choices=["trigram", "canonical"], default="canonical")
    parser.add_argument("--threshold",      type=float, default=0.70)
    parser.add_argument("--ignore",         default="ignore.csv")
    args = parser.parse_args()

    try:
        new_records,  new_fields  = read_csv(args.input,    REQUIRED_COLS)
        exist_records, exist_fields = read_csv(args.existing, REQUIRED_COLS)
    except (FileNotFoundError, ValueError) as exc:
        sys.exit(f"ERROR: {exc}")

    ignore_set = load_ignore(args.ignore)

    cross_pairs = find_cross_pairs(
        new_records, exist_records,
        args.method, args.threshold, ignore_set,
    )

    # IDs of new records that matched at least one existing record
    matched_ids = {new_rec[COL_ID] for new_rec, _, _ in cross_pairs}

    # OK: new records with no match
    ok_records = [r for r in new_records if r[COL_ID] not in matched_ids]

    # possible_errors: one row per (new, existing) pair
    exist_fields_prefixed = [f"exist_{c}" for c in exist_fields]
    error_fieldnames = new_fields + exist_fields_prefixed + ["overall_score"]

    error_rows = []
    for new_rec, exist_rec, score in cross_pairs:
        row = dict(new_rec)
        for col in exist_fields:
            row[f"exist_{col}"] = exist_rec[col]
        row["overall_score"] = score
        error_rows.append(row)

    write_csv(args.ok_output,     ok_records,  new_fields)
    write_csv(args.errors_output, error_rows,  error_fieldnames)

    print(f"New records:     {len(new_records)}")
    print(f"Existing:        {len(exist_records)}")
    print(f"Method:          {args.method}  threshold: {args.threshold}")
    if ignore_set:
        print(f"Ignored pairs:   {len(ignore_set)}")
    print(f"OK:              {len(ok_records)}  → {args.ok_output}")
    print(f"Possible errors: {len(error_rows)}  → {args.errors_output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

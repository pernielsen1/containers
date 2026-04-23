#!/usr/bin/env python3
"""
init_counterparties.py — Bootstrap counterparties.csv from a source CSV.

For each group of records that look like duplicates, only the first record
(by position in the input file) is kept.  All others are dropped.

Usage:
  python3 init_counterparties.py <input.csv> [options]

Options:
  --output      Output CSV path           (default: counterparties.csv)
  --method      trigram | canonical       (default: trigram)
  --threshold   Overall score 0–1         (default: 0.70)
  --ignore      Path to ignore.csv        (default: ignore.csv)
"""

import argparse
import sys

from duplicate_utils import (
    REQUIRED_COLS, COL_ID,
    read_csv, write_csv,
    find_duplicate_pairs, build_group_ids, load_ignore,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deduplicate a counterparty CSV, keeping the first of each duplicate group."
    )
    parser.add_argument("input", help="Source CSV (semicolon-delimited, utf-8-sig)")
    parser.add_argument("--output",    default="counterparties.csv")
    parser.add_argument("--method",    choices=["trigram", "canonical"], default="trigram")
    parser.add_argument("--threshold", type=float, default=0.70)
    parser.add_argument("--ignore",    default="ignore.csv")
    args = parser.parse_args()

    try:
        records, fieldnames = read_csv(args.input, REQUIRED_COLS)
    except (FileNotFoundError, ValueError) as exc:
        sys.exit(f"ERROR: {exc}")

    if not records:
        sys.exit("ERROR: input file is empty")

    ignore_set = load_ignore(args.ignore)

    pairs = find_duplicate_pairs(records, args.method, args.threshold, ignore_set)

    # Build union-find groups from the duplicate pairs found
    id_pairs = [(a[COL_ID], b[COL_ID]) for a, b, _ in pairs]
    group_ids = build_group_ids(id_pairs)

    # Walk records in original order; keep only the first record seen per group
    seen_groups: set = set()
    kept = []
    dropped = []
    for rec in records:
        rec_id = rec[COL_ID]
        group_root = group_ids.get(rec_id, rec_id)
        if group_root not in seen_groups:
            seen_groups.add(group_root)
            kept.append(rec)
        else:
            dropped.append(rec)

    write_csv(args.output, kept, fieldnames)

    print(f"Input records:   {len(records)}")
    print(f"Duplicate pairs: {len(pairs)}")
    print(f"Records dropped: {len(dropped)}")
    print(f"Records kept:    {len(kept)}")
    print(f"Method:          {args.method}  threshold: {args.threshold}")
    if ignore_set:
        print(f"Ignored pairs:   {len(ignore_set)}")
    print(f"Output:          {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

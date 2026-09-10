#!/usr/bin/env python3
"""
sas7bdat_to_csv_utf8.py

Reads a SAS .sas7bdat dataset and writes it out as a UTF-8 CSV --
skips the manual "right-click export" / session-encoding fight
described in sas_blues_fix.md, for an initial Python porting step.

Usage:
    python3 sas7bdat_to_csv_utf8.py input.sas7bdat output.csv
    python3 sas7bdat_to_csv_utf8.py input.sas7bdat output.csv --sas-encoding latin1
"""
import argparse
from pathlib import Path

import pandas as pd


def read_sas7bdat(path, sas_encoding=None):
    """Prefer pyreadstat (more reliable SAS encoding handling) if it's
    installed; fall back to pandas' built-in reader otherwise."""
    try:
        import pyreadstat
        df, _meta = pyreadstat.read_sas7bdat(str(path), encoding=sas_encoding)
        return df
    except ImportError:
        kwargs = {"format": "sas7bdat"}
        if sas_encoding:
            kwargs["encoding"] = sas_encoding
        return pd.read_sas(path, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="path to the .sas7bdat file")
    parser.add_argument("output", type=Path, help="path to write the .csv file")
    parser.add_argument(
        "--sas-encoding",
        default=None,
        help="override SAS's own encoding metadata if auto-detection garbles "
             "characters (e.g. latin1, cp1252) -- try this first if output looks wrong",
    )
    args = parser.parse_args()

    df = read_sas7bdat(args.input, args.sas_encoding)

    print(f"read {len(df)} rows, {len(df.columns)} columns from {args.input.name}")
    print(df.dtypes)

    # Plain comma-separated, dot-decimal UTF-8: this is a porting
    # artifact meant to be re-read by pandas, not opened in Excel --
    # unlike this project's usual ;-separated, ,-decimal convention
    # for Excel-facing CSVs. Pass sep=";", decimal="," to to_csv below
    # if you want an Excel-readable copy instead.
    df.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Generates a "big" CSV with the same schema as sample_data.csv, written
row-by-row with csv.writer -- not built as one giant DataFrame -- so
generating it stays cheap regardless of row count.

Run: python3 generate_big_csv.py [n_rows]  (default 300000)
"""
import argparse
import csv
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config_loader import db_storage_dir

HERE = Path(__file__).resolve().parent

parser = argparse.ArgumentParser()
parser.add_argument("n_rows", nargs="?", type=int, default=300_000)
parser.add_argument("--config", default=str(HERE / "config.json"), help="config.json to use")
args = parser.parse_args()

N_ROWS = args.n_rows

# generated data is disposable/reproducible -- keep it out of the repo,
# next to the db files in db_storage_dir (temp, not synced).
OUT_PATH = db_storage_dir(args.config) / "big_sample.csv"

START_DATE = date(2020, 1, 1)
random.seed(42)

with OUT_PATH.open("w", newline="", encoding="utf-8-sig") as f:
    writer = csv.writer(f, delimiter=";")
    writer.writerow(["key", "num_value", "decimal_value", "the_date", "the_timestamp", "a_value"])

    for i in range(N_ROWS):
        the_date = START_DATE + timedelta(days=i % 2000)
        # sprinkle in some missing values, same as the small sample
        num_value = "" if i % 37 == 0 else random.randint(-100, 10_000)
        decimal_value = "" if i % 53 == 0 else round(random.uniform(-1000, 1000), 2)
        date_str = "" if i % 71 == 0 else the_date.isoformat()
        ts_str = "" if i % 91 == 0 else f"{the_date.isoformat()} {i % 24:02d}:{i % 60:02d}:00"
        a_value = "" if i % 41 == 0 else f"val_{i % 500}"
        writer.writerow([f"K{i:07d}", num_value, decimal_value, date_str, ts_str, a_value])

print(f"wrote {N_ROWS:,} rows -> {OUT_PATH}")

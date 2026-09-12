#!/usr/bin/env python3
"""
Builds test/input/{a_cust,c_cust,d_cust}.csv from prod/input's full
fixture data.

Takes the first num_test_entries (from prod/config.json) rows of
a_cust.csv, plus every a_key listed in test/input/usual_suspects.csv
(a hand-maintained list of a_keys that must always be in the test
fixture, regardless of the head(num_test_entries) sample -- edit that
file directly to add/remove one). Then follows the FK chain to pull in
exactly the c_cust and d_cust rows those a_cust rows reference
(referential integrity preserved), plus one "orphan" row per table --
a c_cust row no a_cust row points to, and a d_cust row no c_cust row
points to -- so the test fixture still exercises the no-parent-link
case.

Note: usual_suspects.csv itself lives in test/input but is never
overwritten by this script -- only a_cust/c_cust/d_cust.csv there are
generated output.

Run: python3 build_test_input.py   (then load.sh --env test, or just
run load_test.sh which does both)
"""
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
PROD_DIR = HERE / "prod"
TEST_DIR = HERE / "test"


def read_csv(path):
    return pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=str)


def write_csv(df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, sep=";", index=False, encoding="utf-8-sig")


def main():
    prod_config = json.loads((PROD_DIR / "config.json").read_text(encoding="utf-8"))
    num_test_entries = prod_config["num_test_entries"]

    a_cust = read_csv(PROD_DIR / "input" / "a_cust.csv")
    c_cust = read_csv(PROD_DIR / "input" / "c_cust.csv")
    d_cust = read_csv(PROD_DIR / "input" / "d_cust.csv")

    usual_suspects_path = TEST_DIR / "input" / "usual_suspects.csv"
    if not usual_suspects_path.exists():
        raise SystemExit(f"{usual_suspects_path} not found")
    usual_suspect_keys = set(read_csv(usual_suspects_path)["a_key"])
    missing_suspects = usual_suspect_keys - set(a_cust["a_key"])
    if missing_suspects:
        raise SystemExit(f"usual_suspects.csv references unknown a_key(s) {missing_suspects}")

    sampled = a_cust.head(num_test_entries)
    always_included = a_cust[a_cust["a_key"].isin(usual_suspect_keys)]
    a_test = pd.concat([sampled, always_included]).drop_duplicates(subset="a_key").sort_index()

    linked_c_keys = set(a_test["c_key"].dropna())
    orphan_c_keys = set(c_cust["c_key"]) - set(a_cust["c_key"].dropna())
    # sorted(), not a raw set -- Python randomizes string hash order
    # per-process, so picking "one orphan" off an unsorted set would
    # silently change between runs on identical input.
    c_test_keys = linked_c_keys | set(sorted(orphan_c_keys)[:1])
    c_test = c_cust[c_cust["c_key"].isin(c_test_keys)]

    linked_d_keys = set(c_test["d_key"].dropna())
    orphan_d_keys = set(d_cust["d_key"]) - set(c_cust["d_key"].dropna())
    d_test_keys = linked_d_keys | set(sorted(orphan_d_keys)[:1])
    d_test = d_cust[d_cust["d_key"].isin(d_test_keys)]

    write_csv(a_test, TEST_DIR / "input" / "a_cust.csv")
    write_csv(c_test, TEST_DIR / "input" / "c_cust.csv")
    write_csv(d_test, TEST_DIR / "input" / "d_cust.csv")

    print(
        f"test fixture: {len(a_test)} a_cust, {len(c_test)} c_cust, "
        f"{len(d_test)} d_cust rows -> {TEST_DIR / 'input'}"
    )


if __name__ == "__main__":
    main()

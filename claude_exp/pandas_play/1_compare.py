import json
import os

import pandas as pd

from xlsb_common import read_csv, write_csv

OUTPUT_DIR = "output"
ACPT_DIR = os.path.join(OUTPUT_DIR, "compare", "ACPT")
PROD_DIR = os.path.join(OUTPUT_DIR, "compare", "PROD")
BOTH_DIR = os.path.join(OUTPUT_DIR, "BOTH")
BOTH_CHANGED_DIR = os.path.join(OUTPUT_DIR, "BOTH_CHANGED")
ONLY_ACPT_DIR = os.path.join(OUTPUT_DIR, "ONLY_ACPT")
ONLY_PROD_DIR = os.path.join(OUTPUT_DIR, "ONLY_PROD")


def load_schema(path: str = "schema.json") -> dict:
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def _read_csv(path: str) -> pd.DataFrame:
    return read_csv(path, dtype=str)


def _write_csv(df: pd.DataFrame, out_dir: str, filename: str) -> None:
    if df.empty:
        return
    os.makedirs(out_dir, exist_ok=True)
    write_csv(df, os.path.join(out_dir, filename))


def _split_matched(acpt_df: pd.DataFrame, prod_df: pd.DataFrame, key_columns: list) -> tuple:
    prod_keys = prod_df[key_columns].drop_duplicates()
    acpt_marked = acpt_df.merge(prod_keys, on=key_columns, how="left", indicator=True)
    both_df = acpt_marked[acpt_marked["_merge"] == "both"].drop(columns="_merge")
    only_acpt_df = acpt_marked[acpt_marked["_merge"] == "left_only"].drop(columns="_merge")

    acpt_keys = acpt_df[key_columns].drop_duplicates()
    prod_marked = prod_df.merge(acpt_keys, on=key_columns, how="left", indicator=True)
    only_prod_df = prod_marked[prod_marked["_merge"] == "left_only"].drop(columns="_merge")

    return both_df, only_acpt_df, only_prod_df


def _find_changed(
    acpt_df: pd.DataFrame, prod_df: pd.DataFrame, key_columns: list, attribute_columns: list
) -> pd.DataFrame:
    if not attribute_columns:
        return pd.DataFrame()

    merged = acpt_df.merge(prod_df, on=key_columns, how="inner", suffixes=("_ACPT", "_PROD"))

    diff_mask = pd.Series(False, index=merged.index)
    for col in attribute_columns:
        acpt_col, prod_col = merged[f"{col}_ACPT"], merged[f"{col}_PROD"]
        same = acpt_col.eq(prod_col) | (acpt_col.isna() & prod_col.isna())
        diff_mask |= ~same

    changed_df = merged[diff_mask]
    if changed_df.empty:
        return changed_df

    ordered_columns = list(key_columns)
    for col in attribute_columns:
        ordered_columns += [f"{col}_ACPT", f"{col}_PROD"]
    return changed_df[ordered_columns]


def compare(schema: dict) -> None:
    acpt_files = set(os.listdir(ACPT_DIR)) if os.path.isdir(ACPT_DIR) else set()
    prod_files = set(os.listdir(PROD_DIR)) if os.path.isdir(PROD_DIR) else set()

    for filename in sorted(acpt_files | prod_files):
        in_acpt = filename in acpt_files
        in_prod = filename in prod_files

        if in_acpt and not in_prod:
            _write_csv(_read_csv(os.path.join(ACPT_DIR, filename)), ONLY_ACPT_DIR, filename)
            continue
        if in_prod and not in_acpt:
            _write_csv(_read_csv(os.path.join(PROD_DIR, filename)), ONLY_PROD_DIR, filename)
            continue

        if filename not in schema:
            raise ValueError(f"No schema entry defined for '{filename}' in schema.json")
        key_columns = schema[filename]["keys"]
        ignore_columns = schema[filename].get("ignore", [])

        acpt_df = _read_csv(os.path.join(ACPT_DIR, filename))
        prod_df = _read_csv(os.path.join(PROD_DIR, filename))
        acpt_df = acpt_df.drop(columns=[c for c in ignore_columns if c in acpt_df.columns])
        prod_df = prod_df.drop(columns=[c for c in ignore_columns if c in prod_df.columns])

        attribute_columns = [
            c for c in acpt_df.columns if c not in key_columns and c in prod_df.columns
        ]

        both_df, only_acpt_df, only_prod_df = _split_matched(acpt_df, prod_df, key_columns)
        changed_df = _find_changed(acpt_df, prod_df, key_columns, attribute_columns)

        _write_csv(both_df, BOTH_DIR, filename)
        _write_csv(changed_df, BOTH_CHANGED_DIR, filename)
        _write_csv(only_acpt_df, ONLY_ACPT_DIR, filename)
        _write_csv(only_prod_df, ONLY_PROD_DIR, filename)


if __name__ == "__main__":
    schema = load_schema()
    compare(schema)
    print("Done.")

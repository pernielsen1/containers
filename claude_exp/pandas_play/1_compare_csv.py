import os
import pandas as pd

from config_utils import load_config

OUTPUT_DIR = "output"
COMPARE_DIR = os.path.join(OUTPUT_DIR, "compare")


def discover_areas(output_dir: str, source_label: str) -> set:
    suffix = f"_{source_label}.csv"
    return {
        fname[: -len(suffix)]
        for fname in os.listdir(output_dir)
        if fname.endswith(suffix)
    }


def _read_area_csv(output_dir: str, area: str, source_label: str, columns: list) -> pd.DataFrame:
    path = os.path.join(output_dir, f"{area}_{source_label}.csv")
    if not os.path.exists(path):
        return pd.DataFrame(columns=columns)
    return pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=str)


def _group_rows(df: pd.DataFrame, key_columns: list) -> dict:
    groups = {}
    for key, group in df.groupby(key_columns, sort=False):
        key_tuple = key if isinstance(key, tuple) else (key,)
        groups[key_tuple] = group
    return groups


def _value_multiset(group: pd.DataFrame, value_columns: list) -> list:
    return sorted(group[value_columns].itertuples(index=False, name=None))


def _append(df: pd.DataFrame, columns: list, path: str, written: set):
    if df.empty:
        return
    first_write = path not in written
    if first_write:
        written.add(path)
    df[columns].to_csv(
        path,
        mode="w" if first_write else "a",
        header=first_write,
        index=False,
        sep=";",
        encoding="utf-8-sig",
    )


def compare(output_dir: str, key_columns: list, value_columns: list) -> dict:
    os.makedirs(COMPARE_DIR, exist_ok=True)
    paths = {
        "only_in_acpt": os.path.join(COMPARE_DIR, "only_in_acpt.csv"),
        "only_in_prod": os.path.join(COMPARE_DIR, "only_in_prod.csv"),
        "differs": os.path.join(COMPARE_DIR, "differs.csv"),
    }
    written = set()

    all_columns = key_columns + value_columns
    acpt_areas = discover_areas(output_dir, "ACPT")
    prod_areas = discover_areas(output_dir, "PROD")

    for area in sorted(acpt_areas | prod_areas):
        acpt_df = _read_area_csv(output_dir, area, "ACPT", all_columns)
        prod_df = _read_area_csv(output_dir, area, "PROD", all_columns)

        acpt_groups = _group_rows(acpt_df, key_columns)
        prod_groups = _group_rows(prod_df, key_columns)

        only_acpt_parts, only_prod_parts, differ_rows = [], [], []

        for key in acpt_groups.keys() | prod_groups.keys():
            acpt_group = acpt_groups.get(key)
            prod_group = prod_groups.get(key)

            if prod_group is None:
                only_acpt_parts.append(acpt_group)
                continue
            if acpt_group is None:
                only_prod_parts.append(prod_group)
                continue

            acpt_values = _value_multiset(acpt_group, value_columns)
            prod_values = _value_multiset(prod_group, value_columns)
            if acpt_values != prod_values:
                row = dict(zip(key_columns, key))
                for i, col in enumerate(value_columns):
                    row[f"{col}_acpt"] = ",".join(str(v[i]) for v in acpt_values)
                    row[f"{col}_prod"] = ",".join(str(v[i]) for v in prod_values)
                differ_rows.append(row)

        if only_acpt_parts:
            out = pd.concat(only_acpt_parts)[all_columns].rename(
                columns={c: f"{c}_acpt" for c in value_columns}
            )
            _append(out, list(out.columns), paths["only_in_acpt"], written)

        if only_prod_parts:
            out = pd.concat(only_prod_parts)[all_columns].rename(
                columns={c: f"{c}_prod" for c in value_columns}
            )
            _append(out, list(out.columns), paths["only_in_prod"], written)

        if differ_rows:
            out = pd.DataFrame(differ_rows)
            columns = key_columns + [f"{c}_acpt" for c in value_columns] + [f"{c}_prod" for c in value_columns]
            _append(out, columns, paths["differs"], written)

    return paths


if __name__ == "__main__":
    config = load_config()
    pattern_cfg = config["file_patterns"][0]

    paths = compare(OUTPUT_DIR, pattern_cfg["key_columns"], pattern_cfg["value_columns"])
    for label, path in paths.items():
        exists = os.path.exists(path)
        print(f"{label}: {path}" + ("" if exists else " (no differences)"))
    print("Done.")

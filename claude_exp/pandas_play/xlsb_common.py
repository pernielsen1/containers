import os

import pandas as pd

# utf-8-sig writes a BOM so Excel renders non-ASCII (ä, ö, ü, ß, å, etc.)
# correctly instead of as mojibake; semicolon avoids clashing with the comma
# decimal separator used in European locales.
CSV_SEP = ";"
CSV_ENCODING = "utf-8-sig"


def write_csv(df: pd.DataFrame, filepath: str, mode: str = "w", header: bool = True) -> None:
    df.to_csv(filepath, mode=mode, header=header, index=False, sep=CSV_SEP, encoding=CSV_ENCODING)


def read_csv(filepath: str, dtype=str) -> pd.DataFrame:
    return pd.read_csv(filepath, sep=CSV_SEP, encoding=CSV_ENCODING, dtype=dtype)


def clean_value(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def to_str(value) -> str:
    return str(clean_value(value))


def safe_filename(value: str) -> str:
    return "".join(c if c.isalnum() or c in " -_." else "_" for c in value)


def check_no_upcast(df: pd.DataFrame) -> None:
    for col in df.columns:
        series = df[col]
        if pd.api.types.is_float_dtype(series) and series.isna().any():
            non_null = series.dropna()
            if not non_null.empty and (non_null % 1 == 0).any():
                raise ValueError(
                    f"Column '{col}' mixes missing values with whole-number floats in "
                    "this chunk; pandas upcast integers back to float, which would "
                    "silently write a '.0' suffix."
                )


def find_source_files(input_dir: str) -> dict:
    acpt = [f for f in os.listdir(input_dir) if "acpt" in f.lower()]
    prod = [f for f in os.listdir(input_dir) if "prod" in f.lower()]
    if len(acpt) != 1:
        raise ValueError(f"Expected exactly one ACPT file in {input_dir}, found {acpt}")
    if len(prod) != 1:
        raise ValueError(f"Expected exactly one PROD file in {input_dir}, found {prod}")
    return {"ACPT": os.path.join(input_dir, acpt[0]), "PROD": os.path.join(input_dir, prod[0])}

"""
Shared read step for the csv -> sqlite examples.

Philosophy: read everything as string first (dtype=str), turn "" into
real None, and only THEN convert the handful of columns that actually
need interpreting. Everything else stays untouched str/None -- no
implicit inference, no NaN traps.
"""
import pandas as pd


def read_all_str_csv(csv_path):
    """Read a CSV with every column as plain string/None -- no
    inference at all. Use this directly for tables that are all-str
    (e.g. a reference/lookup table); read_typed_csv builds on top of
    this for tables that need a few columns converted."""
    df = pd.read_csv(csv_path, sep=";", encoding="utf-8-sig", dtype=str)

    # normalize "" -> None uniformly
    df = df.where(df.notna() & (df != ""), None)
    return df


def read_typed_csv(csv_path):
    df = read_all_str_csv(csv_path)

    # --- only these columns need interpreting ---
    # nullable Int64 keeps missing values as <NA> instead of silently
    # upgrading the whole column to float64 (the classic "int becomes
    # 1.0" side effect of plain pandas + NaN).
    df["num_value"] = pd.to_numeric(df["num_value"], errors="raise").astype("Int64")
    df["decimal_value"] = pd.to_numeric(df["decimal_value"], errors="raise").astype(float)
    df["the_date"] = pd.to_datetime(df["the_date"], format="%Y-%m-%d", errors="raise")
    df["the_timestamp"] = pd.to_datetime(
        df["the_timestamp"], format="%Y-%m-%d %H:%M:%S", errors="raise"
    )

    # key, a_value: left as plain strings/None, no conversion needed

    return df


def export_table_to_csv(conn, table_name, out_path):
    """Export a sqlite table to a CSV readable in Excel: ';' separator,
    ',' decimal point, utf-8-sig encoding (BOM for Excel + accents)."""
    df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)

    # pd.read_sql_query returns nullable INTEGER columns as float64
    # (10 -> 10.0), which then prints as "10,0". Cast back to nullable
    # Int64 using the table's own schema, same discipline as the read
    # step: know which columns are really integers, don't let pandas guess.
    schema = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    int_cols = [col[1] for col in schema if col[2].upper() == "INTEGER"]
    for col in int_cols:
        df[col] = df[col].astype("Int64")

    df.to_csv(out_path, sep=";", decimal=",", index=False, encoding="utf-8-sig")


def row_to_sqlite_params(row):
    """Convert one typed pandas row (from itertuples) to plain Python
    values sqlite3 can bind directly."""
    return (
        row.key,
        None if pd.isna(row.num_value) else int(row.num_value),
        None if pd.isna(row.decimal_value) else float(row.decimal_value),
        None if pd.isna(row.the_date) else row.the_date.strftime("%Y-%m-%d"),
        None if pd.isna(row.the_timestamp) else row.the_timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        row.a_value,
    )

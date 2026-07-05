"""
archiver.py

Zips files out of an input directory into timestamped zip archives, records
them in a CSV index, and moves the originals into a "done" directory.

Expects input files to be named "type_key_timestamp.ext", where timestamp
may itself contain underscores (e.g. companyinfo_350575093_20260705_181909.txt).

Restart-safety: every run simply processes whatever is currently in
input_dir. If a run is interrupted after the index has been updated but
before files were moved to done_dir, the next run will re-zip those files
(an extra, unreferenced zip may accumulate in archive_data), but the merge
step into master_archive_index.csv dedupes on (type, key, timestamp,
file_name) so the index never gets duplicate rows.

Usage:
    python3 archiver.py
"""

import json
import os
import shutil
import zipfile
from datetime import datetime, timezone

import pandas as pd

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "archive.json")

INDEX_COLUMNS = ["type", "key", "timestamp", "file_name", "zip_archive_filename"]
MASTER_INDEX_FILENAME = "master_archive_index.csv"
TEMP_INDEX_FILENAME = "temp_index.csv"

CSV_KWARGS = {"sep": ";", "encoding": "utf-8-sig"}


def load_config(path: str = CONFIG_FILE) -> dict:
    """Paths in the config are relative to the project root, i.e. the parent
    directory of wherever the config file itself lives."""
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(path)))
    return {key: os.path.join(project_root, value) for key, value in raw.items()}


def parse_filename(name: str):
    """Return (type, key, timestamp) for a well-formed "type_key_timestamp.ext"
    name, or None if the name doesn't have enough underscore-separated tokens."""
    stem, _ext = os.path.splitext(name)
    tokens = stem.split("_")
    if len(tokens) < 3:
        return None
    return tokens[0], tokens[1], "_".join(tokens[2:])


def list_input_files(input_dir: str) -> list[str]:
    return sorted(
        name for name in os.listdir(input_dir)
        if os.path.isfile(os.path.join(input_dir, name))
    )


def create_zip(archive_data_dir: str, filenames: list[str], input_dir: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    zip_filename = f"archive_{timestamp}.zip"
    zip_path = os.path.join(archive_data_dir, zip_filename)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in filenames:
            zf.write(os.path.join(input_dir, name), arcname=name)
    return zip_filename


def load_master_index(archive_index_dir: str) -> pd.DataFrame:
    path = os.path.join(archive_index_dir, MASTER_INDEX_FILENAME)
    if not os.path.exists(path):
        return pd.DataFrame(columns=INDEX_COLUMNS)
    return pd.read_csv(path, dtype=str, **CSV_KWARGS).fillna("")


def merge_index(archive_index_dir: str, new_rows: list[dict]) -> tuple[int, int]:
    master_df = load_master_index(archive_index_dir)
    existing_keys = set(
        zip(master_df["type"], master_df["key"], master_df["timestamp"], master_df["file_name"])
    )

    rows_to_add = [
        row for row in new_rows
        if (row["type"], row["key"], row["timestamp"], row["file_name"]) not in existing_keys
    ]
    skipped = len(new_rows) - len(rows_to_add)

    if rows_to_add:
        combined = pd.concat([master_df, pd.DataFrame(rows_to_add, columns=INDEX_COLUMNS)], ignore_index=True)
        master_path = os.path.join(archive_index_dir, MASTER_INDEX_FILENAME)
        combined.to_csv(master_path, index=False, **CSV_KWARGS)

    return len(rows_to_add), skipped


def main(config_path: str = CONFIG_FILE) -> None:
    config = load_config(config_path)
    input_dir = config["input_dir"]
    done_dir = config["done_dir"]
    archive_index_dir = config["archive_index"]
    archive_data_dir = config["archive_data"]

    for path in (input_dir, done_dir, archive_index_dir, archive_data_dir):
        os.makedirs(path, exist_ok=True)

    candidates = list_input_files(input_dir)

    valid_files = []
    for name in candidates:
        if parse_filename(name) is None:
            print(f"  WARNING: Skipping malformed filename: {name}")
            continue
        valid_files.append(name)

    if not valid_files:
        print("Nothing to archive.")
        return

    zip_filename = create_zip(archive_data_dir, valid_files, input_dir)
    print(f"Created zip archive: {zip_filename} ({len(valid_files)} file(s))")

    rows = []
    for name in valid_files:
        file_type, key, timestamp = parse_filename(name)
        rows.append({
            "type": file_type,
            "key": key,
            "timestamp": timestamp,
            "file_name": name,
            "zip_archive_filename": zip_filename,
        })

    temp_index_path = os.path.join(archive_index_dir, TEMP_INDEX_FILENAME)
    pd.DataFrame(rows, columns=INDEX_COLUMNS).to_csv(temp_index_path, index=False, **CSV_KWARGS)

    added, skipped = merge_index(archive_index_dir, rows)

    os.remove(temp_index_path)

    for name in valid_files:
        shutil.move(os.path.join(input_dir, name), os.path.join(done_dir, name))

    print(f"Index updated: {added} row(s) added, {skipped} duplicate row(s) skipped.")
    print(f"Moved {len(valid_files)} file(s) to {done_dir}.")


if __name__ == "__main__":
    main()

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
file_name) so the index never gets duplicate rows. The master index itself
is written via a temp-file-then-os.replace so a crash mid-write can never
leave it truncated/corrupted; a leftover .tmp file from an interrupted run
is inert and gets overwritten on the next run.

Usage:
    python3 archiver.py
"""

import json
import os
import shutil
import zipfile
from datetime import datetime, timezone

import pandas as pd


class Archiver:
    CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "archive.json")

    INDEX_COLUMNS = ["type", "key", "timestamp", "file_name", "zip_archive_filename"]
    MASTER_INDEX_FILENAME = "master_archive_index.csv"
    TEMP_INDEX_FILENAME = "temp_index.csv"

    CSV_KWARGS = {"sep": ";", "encoding": "utf-8-sig"}

    def __init__(self, config: str | dict = CONFIG_FILE):
        if isinstance(config, dict):
            self.config_path = None
            resolved = dict(config)
        else:
            self.config_path = config
            resolved = self._load_config(config)
        self.input_dir = resolved["input_dir"]
        self.done_dir = resolved["done_dir"]
        self.archive_index_dir = resolved["archive_index"]
        self.archive_data_dir = resolved["archive_data"]

    @staticmethod
    def _load_config(path: str) -> dict:
        """Paths in the config are relative to the project root, i.e. the
        parent directory of wherever the config file itself lives."""
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(path)))
        return {key: os.path.join(project_root, value) for key, value in raw.items()}

    @staticmethod
    def parse_filename(name: str):
        """Return (type, key, timestamp) for a well-formed "type_key_timestamp.ext"
        name, or None if the name doesn't have enough underscore-separated tokens."""
        stem, _ext = os.path.splitext(name)
        tokens = stem.split("_")
        if len(tokens) < 3:
            return None
        return tokens[0], tokens[1], "_".join(tokens[2:])

    def _list_input_files(self) -> list[str]:
        return sorted(
            name for name in os.listdir(self.input_dir)
            if os.path.isfile(os.path.join(self.input_dir, name))
        )

    def _create_zip(self, filenames: list[str]) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        zip_filename = f"archive_{timestamp}.zip"
        zip_path = os.path.join(self.archive_data_dir, zip_filename)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in filenames:
                zf.write(os.path.join(self.input_dir, name), arcname=name)
        return zip_filename

    def _load_master_index(self) -> pd.DataFrame:
        path = os.path.join(self.archive_index_dir, self.MASTER_INDEX_FILENAME)
        if not os.path.exists(path):
            return pd.DataFrame(columns=self.INDEX_COLUMNS)
        return pd.read_csv(path, dtype=str, **self.CSV_KWARGS).fillna("")

    def _merge_index(self, new_rows: list[dict]) -> tuple[int, int]:
        master_df = self._load_master_index()
        existing_keys = set(
            zip(master_df["type"], master_df["key"], master_df["timestamp"], master_df["file_name"])
        )

        rows_to_add = [
            row for row in new_rows
            if (row["type"], row["key"], row["timestamp"], row["file_name"]) not in existing_keys
        ]
        skipped = len(new_rows) - len(rows_to_add)

        if rows_to_add:
            combined = pd.concat(
                [master_df, pd.DataFrame(rows_to_add, columns=self.INDEX_COLUMNS)], ignore_index=True
            )
            master_path = os.path.join(self.archive_index_dir, self.MASTER_INDEX_FILENAME)
            tmp_path = master_path + ".tmp"
            combined.to_csv(tmp_path, index=False, **self.CSV_KWARGS)
            os.replace(tmp_path, master_path)

        return len(rows_to_add), skipped

    def run(self) -> None:
        for path in (self.input_dir, self.done_dir, self.archive_index_dir, self.archive_data_dir):
            os.makedirs(path, exist_ok=True)

        candidates = self._list_input_files()

        valid_files = []
        for name in candidates:
            if self.parse_filename(name) is None:
                print(f"  WARNING: Skipping malformed filename: {name}")
                continue
            valid_files.append(name)

        if not valid_files:
            print("Nothing to archive.")
            return

        zip_filename = self._create_zip(valid_files)
        print(f"Created zip archive: {zip_filename} ({len(valid_files)} file(s))")

        rows = []
        for name in valid_files:
            file_type, key, timestamp = self.parse_filename(name)
            rows.append({
                "type": file_type,
                "key": key,
                "timestamp": timestamp,
                "file_name": name,
                "zip_archive_filename": zip_filename,
            })

        temp_index_path = os.path.join(self.archive_index_dir, self.TEMP_INDEX_FILENAME)
        pd.DataFrame(rows, columns=self.INDEX_COLUMNS).to_csv(temp_index_path, index=False, **self.CSV_KWARGS)

        added, skipped = self._merge_index(rows)

        os.remove(temp_index_path)

        for name in valid_files:
            shutil.move(os.path.join(self.input_dir, name), os.path.join(self.done_dir, name))

        print(f"Index updated: {added} row(s) added, {skipped} duplicate row(s) skipped.")
        print(f"Moved {len(valid_files)} file(s) to {self.done_dir}.")


if __name__ == "__main__":
    Archiver().run()

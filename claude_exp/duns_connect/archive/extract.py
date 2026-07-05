"""
extract.py

Restores archived files by key. Looks up every row in master_archive_index.csv
whose "key" column matches, pulls the corresponding file out of its zip
archive, and writes it to output_dir under its original archived name
(type_key_timestamp.ext).

Usage:
    python3 extract.py --key <key> [--output_dir <dir>]
"""

import argparse
import json
import os
import zipfile

import pandas as pd


class Extract:
    CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "archive.json")

    INDEX_COLUMNS = ["type", "key", "timestamp", "file_name", "zip_archive_filename"]
    MASTER_INDEX_FILENAME = "master_archive_index.csv"

    CSV_KWARGS = {"sep": ";", "encoding": "utf-8-sig"}

    def __init__(self, key: str, output_dir: str | None = None, config: str | dict = CONFIG_FILE):
        if isinstance(config, dict):
            self.config_path = None
            resolved = dict(config)
        else:
            self.config_path = config
            resolved = self._load_config(config)

        if "archive_index" not in resolved or "archive_data" not in resolved:
            raise ValueError('config must contain "archive_index" and "archive_data"')

        self.key = key
        self.archive_index_dir = resolved["archive_index"]
        self.archive_data_dir = resolved["archive_data"]
        self.output_dir = output_dir or resolved.get("output_dir")
        if not self.output_dir:
            raise ValueError("output_dir must be passed or configured in the config")

    @staticmethod
    def _load_config(path: str) -> dict:
        """Paths in the config are relative to the project root, i.e. the
        parent directory of wherever the config file itself lives."""
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(path)))
        return {key: os.path.join(project_root, value) for key, value in raw.items()}

    def _load_master_index(self) -> pd.DataFrame:
        path = os.path.join(self.archive_index_dir, self.MASTER_INDEX_FILENAME)
        if not os.path.exists(path):
            return pd.DataFrame(columns=self.INDEX_COLUMNS)
        return pd.read_csv(path, dtype=str, **self.CSV_KWARGS).fillna("")

    def run(self) -> int:
        os.makedirs(self.output_dir, exist_ok=True)

        index_df = self._load_master_index()
        matches = index_df[index_df["key"] == self.key]

        if matches.empty:
            print(f"No entries found for key: {self.key}")
            return 0

        extracted = 0
        for _, row in matches.iterrows():
            zip_path = os.path.join(self.archive_data_dir, row["zip_archive_filename"])
            dest_path = os.path.join(self.output_dir, row["file_name"])
            with zipfile.ZipFile(zip_path) as zf, zf.open(row["file_name"]) as src:
                with open(dest_path, "wb") as dst:
                    dst.write(src.read())
            extracted += 1
            print(f"Extracted {row['file_name']} from {row['zip_archive_filename']}")

        print(f"Extracted {extracted} file(s) for key {self.key} into {self.output_dir}.")
        return extracted


def _parse_args():
    parser = argparse.ArgumentParser(description="Extract archived files by key.")
    parser.add_argument("--key", required=True, help="Key to match against master_archive_index.csv")
    parser.add_argument("--output_dir", default=None, help="Directory to write extracted files into")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    Extract(key=args.key, output_dir=args.output_dir).run()

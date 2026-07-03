import os
import pandas as pd
from pyxlsb import open_workbook

from config_utils import load_config, match_pattern_config


class XlsbToCSV:
    def __init__(
        self,
        input_file: str,
        area_field_name: str,
        source_label: str,
        output_dir: str = "output",
        chunk_size: int = 50_000,
    ):
        self.input_file = input_file
        self.area_field_name = area_field_name
        self.source_label = source_label
        self.output_dir = output_dir
        self.chunk_size = chunk_size

    @staticmethod
    def _clean_value(value):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value

    @classmethod
    def _to_str(cls, value) -> str:
        return str(cls._clean_value(value))

    def _safe_filename(self, value: str) -> str:
        return "".join(c if c.isalnum() or c in " -_." else "_" for c in value)

    def process(self):
        written_files = set()

        with open_workbook(self.input_file) as wb:
            for sheet_name in wb.sheets:
                with wb.get_sheet(sheet_name) as sheet:
                    rows_iter = iter(sheet.rows())
                    try:
                        header_row = next(rows_iter)
                    except StopIteration:
                        continue

                    headers = [cell.v for cell in header_row]

                    if self.area_field_name not in headers:
                        raise ValueError(
                            f"Column '{self.area_field_name}' not found in sheet '{sheet_name}'. "
                            f"Available: {headers}"
                        )
                    area_idx = headers.index(self.area_field_name)

                    chunk = []
                    for row in rows_iter:
                        chunk.append([self._clean_value(cell.v) for cell in row])
                        if len(chunk) >= self.chunk_size:
                            self._write_chunk(chunk, headers, area_idx, written_files)
                            chunk = []
                    if chunk:
                        self._write_chunk(chunk, headers, area_idx, written_files)

    @staticmethod
    def _check_no_upcast(df: pd.DataFrame) -> None:
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

    def _write_chunk(self, rows: list, headers: list, area_idx: int, written_files: set):
        df = pd.DataFrame(rows, columns=headers)
        self._check_no_upcast(df)
        df[self.area_field_name] = df[self.area_field_name].map(self._to_str)

        for area_value, group in df.groupby(self.area_field_name, sort=False):
            filename = f"{self._safe_filename(area_value)}_{self.source_label}.csv"
            filepath = os.path.join(self.output_dir, filename)

            first_write = filepath not in written_files
            if first_write:
                written_files.add(filepath)

            group.to_csv(
                filepath,
                mode="w" if first_write else "a",
                header=first_write,
                index=False,
                sep=";",
                encoding="utf-8-sig",
            )


def find_source_files(input_dir: str) -> dict:
    acpt = [f for f in os.listdir(input_dir) if "acpt" in f.lower()]
    prod = [f for f in os.listdir(input_dir) if "prod" in f.lower()]
    if len(acpt) != 1:
        raise ValueError(f"Expected exactly one ACPT file in {input_dir}, found {acpt}")
    if len(prod) != 1:
        raise ValueError(f"Expected exactly one PROD file in {input_dir}, found {prod}")
    return {"ACPT": os.path.join(input_dir, acpt[0]), "PROD": os.path.join(input_dir, prod[0])}


if __name__ == "__main__":
    ONE_DRIVE = "/mnt/c/users/perni/OneDrive/Documents/"
    IN_DIR = os.path.join(ONE_DRIVE, "wsl_input", "test_xlsb")

    config = load_config()
    source_files = find_source_files(IN_DIR)

    for source_label, input_file in source_files.items():
        pattern_cfg = match_pattern_config(input_file, config)
        converter = XlsbToCSV(
            input_file=input_file,
            area_field_name=pattern_cfg["area_field_name"],
            source_label=source_label,
        )
        converter.process()
    print("Done.")

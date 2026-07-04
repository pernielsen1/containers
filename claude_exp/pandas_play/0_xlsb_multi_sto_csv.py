import json
import os

import pandas as pd
from pyxlsb import open_workbook

from xlsb_common import check_no_upcast, clean_value, find_source_files, safe_filename


class XlsbMultiSheetToCSV:
    def __init__(
        self,
        input_file: str,
        sheet_area_map: dict,
        source_label: str,
        output_dir: str = "output",
        chunk_size: int = 50_000,
    ):
        self.input_file = input_file
        self.sheet_area_map = sheet_area_map
        self.source_label = source_label
        self.output_dir = os.path.join(output_dir, "compare", source_label)
        self.chunk_size = chunk_size

    def process(self):
        written_files = set()

        with open_workbook(self.input_file) as wb:
            for sheet_name in wb.sheets:
                if sheet_name not in self.sheet_area_map:
                    continue
                area_name = self.sheet_area_map[sheet_name]

                with wb.get_sheet(sheet_name) as sheet:
                    rows_iter = iter(sheet.rows())
                    try:
                        header_row = next(rows_iter)
                    except StopIteration:
                        continue

                    headers = [cell.v for cell in header_row]

                    chunk = []
                    for row in rows_iter:
                        chunk.append([clean_value(cell.v) for cell in row])
                        if len(chunk) >= self.chunk_size:
                            self._write_chunk(chunk, headers, area_name, written_files)
                            chunk = []
                    if chunk:
                        self._write_chunk(chunk, headers, area_name, written_files)

    def _write_chunk(self, rows: list, headers: list, area_name: str, written_files: set):
        df = pd.DataFrame(rows, columns=headers)
        check_no_upcast(df)

        os.makedirs(self.output_dir, exist_ok=True)

        filename = f"{safe_filename(area_name)}.csv"
        filepath = os.path.join(self.output_dir, filename)

        first_write = filepath not in written_files
        if first_write:
            written_files.add(filepath)

        df.to_csv(
            filepath,
            mode="w" if first_write else "a",
            header=first_write,
            index=False,
            sep=";",
            encoding="utf-8-sig",
        )


if __name__ == "__main__":
    ONE_DRIVE = "/mnt/c/users/perni/OneDrive/Documents/"
    IN_DIR = os.path.join(ONE_DRIVE, "wsl_input", "test_multi_sheet")

    with open("multi_sheets.json", "r", encoding="utf-8") as f:
        sheet_area_map = json.load(f)

    source_files = find_source_files(IN_DIR)

    for source_label, input_file in source_files.items():
        converter = XlsbMultiSheetToCSV(
            input_file=input_file,
            sheet_area_map=sheet_area_map,
            source_label=source_label,
        )
        converter.process()
    print("Done.")

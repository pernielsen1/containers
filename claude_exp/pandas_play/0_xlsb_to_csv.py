import os
import pandas as pd
from pyxlsb import open_workbook

from config_utils import get_input_dir, load_config, match_pattern_config
from xlsb_common import find_source_files, safe_filename, to_str, write_csv


class XlsbToCSV:
    def __init__(
        self,
        input_file: str,
        area_field_name: str,
        key_columns: list,
        value_columns: list,
        source_label: str,
        output_dir: str = "output",
        chunk_size: int = 50_000,
    ):
        self.input_file = input_file
        self.area_field_name = area_field_name
        self.key_columns = key_columns
        self.kept_columns = set(key_columns) | set(value_columns)
        self.source_label = source_label
        self.output_dir = os.path.join(output_dir, "compare", source_label)
        self.chunk_size = chunk_size
        self.rows_written = 0
        self.millions_reported = 0

    def process(self):
        written_files = set()

        with open_workbook(self.input_file) as wb:
            for sheet_name in wb.sheets:
                if not sheet_name.startswith("v"):
                    continue
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
                    output_columns = [h for h in headers if h in self.kept_columns]

                    chunk = []
                    for row in rows_iter:
                        chunk.append([to_str(cell.v) for cell in row])
                        if len(chunk) >= self.chunk_size:
                            self._write_chunk(chunk, headers, output_columns, written_files)
                            self._report_progress(len(chunk))
                            chunk = []
                    if chunk:
                        self._write_chunk(chunk, headers, output_columns, written_files)
                        self._report_progress(len(chunk))

        if self.rows_written:
            print()

    def _report_progress(self, chunk_len: int) -> None:
        self.rows_written += chunk_len
        print(".", end="", flush=True)
        while self.rows_written // 1_000_000 > self.millions_reported:
            self.millions_reported += 1
            print(self.millions_reported)

    def _write_chunk(self, rows: list, headers: list, output_columns: list, written_files: set):
        df = pd.DataFrame(rows, columns=headers).sort_values(self.key_columns)

        os.makedirs(self.output_dir, exist_ok=True)

        for area_value, group in df.groupby(self.area_field_name, sort=False):
            filename = f"{safe_filename(area_value)}.csv"
            filepath = os.path.join(self.output_dir, filename)

            first_write = filepath not in written_files
            if first_write:
                written_files.add(filepath)

            write_csv(group[output_columns], filepath, mode="w" if first_write else "a", header=first_write)


if __name__ == "__main__":
    config = load_config()
    IN_DIR = get_input_dir(config, "xlsb_to_csv")

    source_files = find_source_files(IN_DIR)

    for source_label, input_file in source_files.items():
        pattern_cfg = match_pattern_config(input_file, config)
        converter = XlsbToCSV(
            input_file=input_file,
            area_field_name=pattern_cfg["area_field_name"],
            key_columns=pattern_cfg["key_columns"],
            value_columns=pattern_cfg["value_columns"],
            source_label=source_label,
        )
        converter.process()
    print("Done.")

import os
import shutil
from pathlib import Path

DEFAULT_PASS2_CSV = Path(__file__).parent.parent / 'output' / 'pass2' / 'extracted.csv'
DEFAULT_FULL_EXTRACT = Path(__file__).parent.parent / 'full_extract.csv'

_CHUNK = 1 << 20  # 1 MB


class Merger:
    def merge(self, pass2_csv: Path, full_extract_csv: Path) -> int:
        tmp = full_extract_csv.parent / (full_extract_csv.name + '.tmp')
        rows_appended = 0

        try:
            existing = full_extract_csv.exists() and full_extract_csv.stat().st_size > 0

            with open(tmp, 'wb') as out:
                if existing:
                    with open(full_extract_csv, 'rb') as src:
                        shutil.copyfileobj(src, out, _CHUNK)

                with open(pass2_csv, 'rb') as src:
                    header = src.readline()
                    if not existing:
                        out.write(header)
                    for line in src:
                        out.write(line)
                        rows_appended += 1

            os.replace(tmp, full_extract_csv)
        except Exception:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise

        return rows_appended

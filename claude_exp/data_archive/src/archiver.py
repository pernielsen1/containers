import gzip
import base64
from pathlib import Path


def compress_to_base64(content: str) -> str:
    compressed = gzip.compress(content.encode('utf-8'))
    return base64.b64encode(compressed).decode('ascii')


def decompress_from_base64(b64: str) -> str:
    compressed = base64.b64decode(b64)
    return gzip.decompress(compressed).decode('utf-8')


def ensure_csv_intact(csv_path: Path) -> None:
    """Truncate any partial last line left by a crash."""
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return
    with open(csv_path, 'rb') as f:
        f.seek(-1, 2)
        last_byte = f.read(1)
    if last_byte == b'\n':
        return
    data = csv_path.read_bytes()
    last_nl = data.rfind(b'\n')
    csv_path.write_bytes(data[:last_nl + 1] if last_nl >= 0 else b'')


def write_header_if_needed(csv_path: Path) -> None:
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        with open(csv_path, 'w', encoding='utf-8-sig') as f:
            f.write('run_id;key;type;suffix;base64_json\n')


def append_to_csv(csv_path: Path, run_id: str, key: str, type_: str, suffix: str, b64: str) -> None:
    with open(csv_path, 'a', encoding='utf-8') as f:
        f.write(f'{run_id};{key};{type_};{suffix};{b64}\n')
        f.flush()

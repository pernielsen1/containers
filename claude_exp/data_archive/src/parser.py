from pathlib import Path


def parse_filename(filename: str) -> tuple[str, str]:
    """Parse 'key_type_xxxx.json' -> (key, type). key and type have no underscores."""
    stem = Path(filename).stem
    parts = stem.split('_', 2)
    if len(parts) < 2:
        raise ValueError(f"Cannot parse key/type from '{filename}': expected key_type_*.json")
    return parts[0], parts[1]

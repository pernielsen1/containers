"""Load db_storage_dir from this example's config.json (creates the
directory if it doesn't exist yet)."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"


def db_storage_dir():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    path = Path(config["db_storage_dir"]).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path

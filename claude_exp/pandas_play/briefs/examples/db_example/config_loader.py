"""Load db_storage_dir from a config.json (creates the directory if it
doesn't exist yet). No default config.json lives here anymore -- every
caller resolves a path first, either via config_path_for_env (prod,
test, or samples -- all shaped db_example/<name>/config.json) or an
explicit path of their own."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def config_path_for_env(env):
    return HERE / env / "config.json"


def db_storage_dir(config_path):
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    storage_path = Path(config["db_storage_dir"]).expanduser()
    storage_path.mkdir(parents=True, exist_ok=True)
    return storage_path

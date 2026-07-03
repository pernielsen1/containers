import fnmatch
import json
import os


def load_config(config_path: str = "config.json") -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def match_pattern_config(filename: str, config: dict) -> dict:
    basename = os.path.basename(filename).lower()
    for entry in config["file_patterns"]:
        if fnmatch.fnmatch(basename, entry["pattern"].lower()):
            return entry
    raise ValueError(f"No config file_pattern matches '{basename}'")

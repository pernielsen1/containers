#!/usr/bin/env python3
"""Scanner daemon: monitors directories and processes files using configured actions."""
import json
import os
import signal
import sys
import time
import fcntl
import shutil
import subprocess
import logging
from datetime import datetime
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config.json"
PID_FILE = Path(__file__).parent / "scanner.pid"
LOG_FILE = Path(__file__).parent / "scanner.log"
SCRIPTS_DIR = Path(__file__).parent
ACTIONS_DIR = Path(__file__).parent / "actions"

MAX_INBOUND_PATH_LEN = 128
_sequence = 0
_reload_requested = False
_shutdown_requested = False


def _handle_sighup(signum, frame):
    global _reload_requested
    _reload_requested = True


def _handle_sigterm(signum, frame):
    global _shutdown_requested
    _shutdown_requested = True


def ensure_action_dirs(config):
    for entry in config.get("directories", []):
        action_script = entry["action"]
        name = Path(action_script).stem
        action_dir = ACTIONS_DIR / name
        action_config = action_dir / "config.json"
        if not action_dir.exists():
            action_dir.mkdir(parents=True)
            with open(action_config, "w", encoding="utf-8") as f:
                json.dump({"name": name}, f, indent=4)
            logging.info("Created action config: %s", action_config)


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def setup_logging():
    handlers = [logging.FileHandler(LOG_FILE)]
    if sys.stdout.isatty():
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )


def ensure_mirror_dirs(config, inbound_path: Path):
    base = Path(config["base_dir"])
    rel = inbound_path.relative_to(base)
    for mirror in (config["pending_dir"], config["log_dir"], config["failed_dir"]):
        (base / mirror / rel).mkdir(parents=True, exist_ok=True)


def try_lock(filepath: Path) -> bool:
    """Return True if an exclusive lock can be obtained on filepath."""
    try:
        with open(filepath, "rb") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
        return True
    except (OSError, IOError):
        return False


def unique_name(original: Path) -> str:
    global _sequence
    _sequence += 1
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{ts}_{_sequence:04d}_{original.name}"


def process_file(config, inbound_path: Path, filepath: Path, action_script: str):
    base = Path(config["base_dir"])
    rel = inbound_path.relative_to(base)

    name = unique_name(filepath)
    pending_dir = base / config["pending_dir"] / rel
    log_dir = base / config["log_dir"] / rel
    failed_dir = base / config["failed_dir"] / rel

    pending_file = pending_dir / name
    shutil.move(str(filepath), str(pending_file))
    logging.info("Moved to pending: %s", pending_file)

    script = SCRIPTS_DIR / action_script
    result = subprocess.run(
        [sys.executable, str(script), str(pending_file)],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        dest = log_dir / name
        shutil.move(str(pending_file), str(dest))
        logging.info("Success -> log: %s", dest)
        if result.stdout:
            logging.info(result.stdout.strip())
    else:
        dest = failed_dir / name
        shutil.move(str(pending_file), str(dest))
        logging.warning("Failed (exit %d) -> failed: %s", result.returncode, dest)
        if result.stderr:
            logging.warning(result.stderr.strip())


def scan_once(config, seen: set, size_cache: dict):
    for entry in config.get("directories", []):
        raw_path = entry["path"]
        action = entry["action"]
        inbound = Path(raw_path)

        if len(raw_path) > MAX_INBOUND_PATH_LEN:
            logging.error("Inbound path exceeds 128 chars, skipping: %s", raw_path)
            continue

        if not inbound.is_dir():
            logging.warning("Inbound dir not found: %s", inbound)
            continue

        ensure_mirror_dirs(config, inbound)

        for filepath in sorted(inbound.iterdir()):
            if not filepath.is_file():
                continue
            key = (str(filepath), filepath.stat().st_ino)
            if key in seen:
                continue

            current_size = filepath.stat().st_size
            previous_size = size_cache.get(str(filepath))
            size_cache[str(filepath)] = current_size
            if previous_size is None or previous_size != current_size:
                logging.debug("Size unstable, waiting next scan: %s", filepath.name)
                continue

            if not try_lock(filepath):
                logging.debug("File locked, skipping: %s", filepath.name)
                continue

            size_cache.pop(str(filepath), None)
            seen.add(key)
            logging.info("Discovered: %s", filepath.name)
            try:
                process_file(config, inbound, filepath, action)
            except Exception as exc:
                logging.exception("Error processing %s: %s", filepath.name, exc)
            if _shutdown_requested:
                return


def write_pid():
    PID_FILE.write_text(str(os.getpid()))


def run():
    setup_logging()
    write_pid()
    logging.info("Scanner started (pid %d)", os.getpid())

    signal.signal(signal.SIGHUP, _handle_sighup)
    signal.signal(signal.SIGTERM, _handle_sigterm)

    config = load_config()
    ensure_action_dirs(config)

    seen: set = set()
    size_cache: dict = {}
    while True:
        global _reload_requested, _shutdown_requested
        if _reload_requested:
            _reload_requested = False
            logging.info("Reloading configuration...")
            config = load_config()
            ensure_action_dirs(config)
            logging.info("Configuration reloaded.")
        try:
            scan_once(config, seen, size_cache)
        except Exception as exc:
            logging.exception("Scan error: %s", exc)
        if _shutdown_requested:
            logging.info("Shutdown requested — exiting cleanly.")
            PID_FILE.unlink(missing_ok=True)
            sys.exit(0)
        interval = config.get("scan_interval_seconds", 5)
        shutdown_timeout = config.get("shutdown_timeout_seconds", 30)
        deadline = min(interval, shutdown_timeout)
        for _ in range(deadline):
            if _shutdown_requested:
                break
            time.sleep(1)


if __name__ == "__main__":
    run()

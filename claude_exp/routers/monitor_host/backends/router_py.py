"""router_py backend: every actor type is a plain host subprocess (router_py has no Docker
container of its own actors, unlike router_java/router_cpp) - so CONTAINER_NAME is None and
HOST_SUBPROCESS_TYPES covers all four actor types, not just upstream/downstream."""
import json
import os
import sys
from pathlib import Path

ROUTERS_ROOT = Path(__file__).resolve().parent.parent.parent
PROJECT_ROOT = ROUTERS_ROOT / "router_py"
UPSTREAM_HOST_DIR = ROUTERS_ROOT / "upstream_host"
DOWNSTREAM_HOST_DIR = ROUTERS_ROOT / "downstream_host"

CONTAINER_NAME = None
HOST_SUBPROCESS_TYPES = {"router", "crypto", "upstream", "downstream"}

SCRIPTS_BY_TYPE = {
    "router": PROJECT_ROOT / "router" / "main.py",
    "upstream": UPSTREAM_HOST_DIR / "main.py",
    "downstream": DOWNSTREAM_HOST_DIR / "main.py",
    "crypto": PROJECT_ROOT / "simulators" / "crypto_host" / "main.py",
}
CONFIG_REQUIRED_TYPES = {"router", "upstream", "downstream"}
STARTUP_ORDER = {"crypto": 0, "downstream": 1, "router": 2, "upstream": 3}


def discover_actors():
    found = []
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "old") and not d.startswith(".")]
        if "config.json" not in files:
            continue
        path = os.path.join(root, "config.json")
        try:
            with open(path) as f:
                cfg = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue

        name = cfg.get("name")
        actor_type = cfg.get("type")
        if not name or actor_type not in SCRIPTS_BY_TYPE:
            continue

        found.append({
            "name": name,
            "type": actor_type,
            "command_port": cfg.get("command_port"),
            "config_path": path,
            "is_active": cfg.get("is_active", True),
            "partner_id": cfg.get("partner_id"),
            "auth_token": cfg.get("command_auth_token"),
        })

    # The walk above only ever covers PROJECT_ROOT (router_py/), so it can never find
    # upstream_host's config - it lives in the shared routers/upstream_host/ directory, outside
    # this tree entirely. Add it explicitly.
    upstream_config_path = UPSTREAM_HOST_DIR / "config.json"
    try:
        with open(upstream_config_path) as f:
            upstream_cfg = json.load(f)
        found.append({
            "name": upstream_cfg.get("name"),
            "type": upstream_cfg.get("type"),
            "command_port": upstream_cfg.get("command_port"),
            "config_path": str(upstream_config_path),
            "is_active": upstream_cfg.get("is_active", True),
            "partner_id": upstream_cfg.get("partner_id"),
            "auth_token": upstream_cfg.get("command_auth_token"),
        })
    except (OSError, json.JSONDecodeError):
        pass

    found.sort(key=lambda a: STARTUP_ORDER.get(a["type"], 99))
    return found


def host_subprocess_cmd(actor):
    script = SCRIPTS_BY_TYPE[actor["type"]]
    cmd = [sys.executable, str(script)]
    if actor["type"] in CONFIG_REQUIRED_TYPES:
        cmd += ["--config", actor["config_path"]]
    return cmd, str(PROJECT_ROOT)


def launch_docker_actor(actor):
    raise RuntimeError("router_py backend has no docker-exec actor types")


def docker_actor_commands(actor):
    raise RuntimeError("router_py backend has no docker-exec actor types")

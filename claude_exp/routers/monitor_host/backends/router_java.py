"""router_java backend: router/crypto actor types run via `docker exec -d` into the already-built
router_java container (see routers/router_java/start.sh); upstream/downstream are the shared
upstream_host/downstream_host components, always plain host subprocesses regardless of target."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROUTERS_ROOT = Path(__file__).resolve().parent.parent.parent
PROJECT_ROOT = ROUTERS_ROOT / "router_java"
UPSTREAM_HOST_DIR = ROUTERS_ROOT / "upstream_host"
DOWNSTREAM_HOST_DIR = ROUTERS_ROOT / "downstream_host"
HOST_DIR_BY_TYPE = {"upstream": UPSTREAM_HOST_DIR, "downstream": DOWNSTREAM_HOST_DIR}

CONTAINER_NAME = "router_java"
HOST_SUBPROCESS_TYPES = {"upstream", "downstream"}

MAIN_CLASS_BY_TYPE = {
    "router": "com.router.router.RouterMain",
    "crypto": "com.router.simulators.cryptohost.CryptoHostMain",
}
STARTUP_ORDER = {"crypto": 0, "downstream": 1, "router": 2, "upstream": 3}


def discover_actors():
    found = []
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in ("target", "old") and not d.startswith(".")]
        # router_java keeps all actor configs as config/<name>.json rather than one config.json
        # per actor directory - check every *.json under config/ too.
        if os.path.basename(root) == "config":
            for fn in files:
                if fn.endswith(".json"):
                    _consider(found, os.path.join(root, fn))
        if "config.json" in files:
            _consider(found, os.path.join(root, "config.json"))

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


def _consider(found, path):
    try:
        with open(path) as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        return
    name = cfg.get("name")
    actor_type = cfg.get("type")
    if not name or (actor_type not in MAIN_CLASS_BY_TYPE and actor_type not in HOST_SUBPROCESS_TYPES):
        return
    if any(a["name"] == name for a in found):
        return
    found.append({
        "name": name,
        "type": actor_type,
        "command_port": cfg.get("command_port"),
        "config_path": path,
        "is_active": cfg.get("is_active", True),
        "partner_id": cfg.get("partner_id"),
        "auth_token": cfg.get("command_auth_token"),
    })


def host_subprocess_cmd(actor):
    host_dir = HOST_DIR_BY_TYPE[actor["type"]]
    return [sys.executable, str(host_dir / "main.py"), "--config", actor["config_path"]], str(host_dir)


def launch_docker_actor(actor):
    main_class = MAIN_CLASS_BY_TYPE[actor["type"]]
    rel_config = os.path.relpath(actor["config_path"], PROJECT_ROOT)
    # stdout/stderr redirected to a file inside the container (truncated each launch) so an
    # operator can `docker exec ... tail -F` it by hand - see docker_actor_commands() below.
    java_cmd = (
        f"mkdir -p logs && java -cp target/router_java.jar {main_class} "
        f"--config {rel_config} > logs/{actor['name']}.console.log 2>&1"
    )
    subprocess.run(["docker", "exec", "-d", CONTAINER_NAME, "bash", "-c", java_cmd], check=True, cwd=PROJECT_ROOT)


def docker_actor_commands(actor):
    main_class = MAIN_CLASS_BY_TYPE[actor["type"]]
    rel_config = os.path.relpath(actor["config_path"], PROJECT_ROOT)
    # jps -lm prints "<pid> <main class> <program args>" - matching on class+config together
    # (not just class) disambiguates actors that share a main class but differ by config, e.g.
    # multiple router instances.
    pattern = f"{main_class} --config {rel_config}"
    kill = "\n".join([
        "#!/usr/bin/env bash",
        f'PATTERN="{pattern}"',
        f'PID=$(docker exec {CONTAINER_NAME} jps -lm | grep -F "$PATTERN" | cut -d" " -f1)',
        'if [ -z "$PID" ]; then',
        '  echo "No matching process found for: $PATTERN" >&2',
        "  exit 1",
        "fi",
        'echo "Killing PID $PID ($PATTERN)"',
        f'docker exec {CONTAINER_NAME} kill -9 "$PID"',
    ])
    tail = f"docker exec {CONTAINER_NAME} tail -F logs/{actor['name']}.console.log"
    return {"kill": kill, "tail": tail}

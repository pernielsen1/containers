"""router_cpp backend: router/crypto actor types run via `docker exec -d` into the already-built
router_cpp container (see routers/router_cpp/start.sh); upstream/downstream are the shared
upstream_host/downstream_host components, always plain host subprocesses regardless of target.

Unlike router_py/router_java (one config.json per actor directory), router_cpp keeps one shared
config/router_1.json read by all four binaries - "discovery" here means synthesizing four logical
actor descriptors from that single file's nested upstream/downstream/crypto blocks."""
import json
import subprocess
import sys
from pathlib import Path

ROUTERS_ROOT = Path(__file__).resolve().parent.parent.parent
PROJECT_ROOT = ROUTERS_ROOT / "router_cpp"
UPSTREAM_HOST_DIR = ROUTERS_ROOT / "upstream_host"
DOWNSTREAM_HOST_DIR = ROUTERS_ROOT / "downstream_host"
HOST_DIR_BY_TYPE = {"upstream": UPSTREAM_HOST_DIR, "downstream": DOWNSTREAM_HOST_DIR}

CONTAINER_NAME = "router_cpp"
HOST_SUBPROCESS_TYPES = {"upstream", "downstream"}
CONFIG_REL_PATH = "config/router_1.json"
CONFIG_ABS_PATH_IN_CONTAINER = "/config/router_1.json"
BUILD_DIR_IN_CONTAINER = "/src/build"
LOGS_DIR_IN_CONTAINER = "/src/logs"

BINARY_BY_TYPE = {"router": "router_main", "crypto": "crypto_host"}
STARTUP_ORDER = {"crypto": 0, "downstream": 1, "router": 2, "upstream": 3}


def discover_actors():
    with open(PROJECT_ROOT / CONFIG_REL_PATH) as f:
        cfg = json.load(f)

    actors = [
        {
            "name": cfg.get("name", "router_1"),
            "type": "router",
            "command_port": cfg.get("command_port", 8080),
            "auth_token": cfg.get("command_auth_token"),
            "partner_id": cfg.get("partner_id"),
            "is_active": True,
            "config_abs_path_in_container": CONFIG_ABS_PATH_IN_CONTAINER,
        },
        {
            "name": "downstream_host",
            "type": "downstream",
            "command_port": cfg.get("downstream", {}).get("command_port", 8081),
            "auth_token": None,
            "partner_id": None,
            "is_active": True,
            # downstream_host deliberately has no shared config.json of its own (see
            # downstream_host/build_router.md) - every implementation keeps its own. router_cpp's
            # lives at config/downstream_host.json, not under downstream_host/ itself.
            "config_path": str(PROJECT_ROOT / "config" / "downstream_host.json"),
        },
        {
            "name": "crypto_host",
            "type": "crypto",
            "command_port": cfg.get("crypto", {}).get("command_port", 8082),
            "auth_token": None,
            "partner_id": None,
            "is_active": True,
            "config_abs_path_in_container": CONFIG_ABS_PATH_IN_CONTAINER,
        },
        {
            "name": "upstream_host",
            "type": "upstream",
            "command_port": cfg.get("upstream", {}).get("command_port", 8083),
            "auth_token": None,
            "partner_id": None,
            "is_active": True,
            "config_path": str(UPSTREAM_HOST_DIR / "config.json"),
        },
    ]
    actors.extend(_load_router_2_actors())
    for a in actors:
        if a["type"] in BINARY_BY_TYPE:
            a["binary"] = BINARY_BY_TYPE[a["type"]]
    actors.sort(key=lambda a: STARTUP_ORDER.get(a["type"], 99))
    return actors


def _load_router_2_actors():
    """router_2/upstream_2: a second, independent router instance + its paired load generator,
    disabled by default (is_active: false in both config files). Unlike router_1, these are NOT
    one-shared-file synthesized descriptors - each gets its own config/router_2.json /
    config/upstream_2.json."""
    actors = []
    router2_path = PROJECT_ROOT / "config" / "router_2.json"
    if not router2_path.exists():
        return actors
    with open(router2_path) as f:
        cfg2 = json.load(f)
    actors.append({
        "name": cfg2.get("name", "router_2"),
        "type": "router",
        "command_port": cfg2.get("command_port", 8085),
        "auth_token": cfg2.get("command_auth_token"),
        "partner_id": cfg2.get("partner_id"),
        "is_active": cfg2.get("is_active", False),
        "config_abs_path_in_container": "/config/router_2.json",
    })

    upstream2_path = PROJECT_ROOT / "config" / "upstream_2.json"
    if upstream2_path.exists():
        with open(upstream2_path) as f:
            ucfg2 = json.load(f)
        actors.append({
            "name": ucfg2.get("name", "upstream_2"),
            "type": "upstream",
            "command_port": ucfg2.get("command_port", 8086),
            "auth_token": None,
            "partner_id": None,
            "is_active": ucfg2.get("is_active", False),
            "config_path": str(upstream2_path),
        })
    return actors


def host_subprocess_cmd(actor):
    host_dir = HOST_DIR_BY_TYPE[actor["type"]]
    config_path = actor.get("config_path") or str(host_dir / "config.json")
    return [sys.executable, str(host_dir / "main.py"), "--config", config_path], str(host_dir)


def launch_docker_actor(actor):
    binary_path = f"{BUILD_DIR_IN_CONTAINER}/{actor['binary']}"
    cmd = (
        f"mkdir -p {LOGS_DIR_IN_CONTAINER} && "
        f"{binary_path} --config {actor['config_abs_path_in_container']} "
        f"> {LOGS_DIR_IN_CONTAINER}/{actor['name']}.console.log 2>&1"
    )
    subprocess.run(["docker", "exec", "-d", CONTAINER_NAME, "bash", "-c", cmd], check=True)


def docker_actor_commands(actor):
    """Match must be anchored to the start of the command (after stripping the PID column), not a
    bare substring search -- PID 1 is docker-init/tini, and `ps` shows its own argv as the entire
    wrapped shell script text (every actor's invocation concatenated together), which trivially
    contains any single actor's pattern as a substring. A plain `grep -F` would match PID 1 first
    and kill the whole container instead of the intended single actor."""
    binary_path = f"{BUILD_DIR_IN_CONTAINER}/{actor['binary']}"
    pattern = f"{binary_path} --config {actor['config_abs_path_in_container']}"
    kill = (
        f'PATTERN="{pattern}"\n'
        f'PID=$(docker exec {CONTAINER_NAME} sh -c "ps -eo pid,args" | '
        f"awk -v pat=\"$PATTERN\" '{{cmd=$0; sub(/^[ \\t]*[0-9]+[ \\t]+/, \"\", cmd); "
        f"if (index(cmd, pat) == 1) print $1}}')\n"
        f'if [ -z "$PID" ]; then echo "no matching process"; exit 1; fi\n'
        f'docker exec {CONTAINER_NAME} kill -9 "$PID"'
    )
    tail = f"docker exec {CONTAINER_NAME} tail -F {LOGS_DIR_IN_CONTAINER}/{actor['name']}.console.log"
    return {"kill": kill, "tail": tail}

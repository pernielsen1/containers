"""router_java backend: router/crypto actor types run via `docker exec -d` into the already-built
router_java container (see routers/router_java/docker-compose.yml); upstream/downstream are the
shared upstream_host/downstream_host components, always plain host subprocesses regardless of
target.

Container paths differ from host paths: the container only bind-mounts router_java/config/ (at
/config), not the whole project (see docker-compose.yml), and the runtime image has no `target/`
build tree - just /app/router_java.jar. discover_actors() still walks the *host* config/ tree for
discovery; CONFIG_ABS_PATH_IN_CONTAINER below maps each discovered config's basename to its
in-container path."""
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
JAR_PATH_IN_CONTAINER = "/app/router_java.jar"
LOGS_DIR_IN_CONTAINER = "/app/logs"

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
        # The container only bind-mounts router_java/config/ at /config (see
        # docker-compose.yml) - every discoverable router/crypto config lives directly under
        # that directory, so its in-container path is just /config/<basename>.
        "config_abs_path_in_container": f"/config/{os.path.basename(path)}",
        "is_active": cfg.get("is_active", True),
        "partner_id": cfg.get("partner_id"),
        "auth_token": cfg.get("command_auth_token"),
    })


def host_subprocess_cmd(actor):
    host_dir = HOST_DIR_BY_TYPE[actor["type"]]
    return [sys.executable, str(host_dir / "main.py"), "--config", actor["config_path"]], str(host_dir)


def launch_docker_actor(actor):
    main_class = MAIN_CLASS_BY_TYPE[actor["type"]]
    # stdout/stderr redirected to a file inside the container (truncated each launch) so an
    # operator can `docker exec ... tail -F` it by hand - see docker_actor_commands() below.
    java_cmd = (
        f"mkdir -p {LOGS_DIR_IN_CONTAINER} && java -cp {JAR_PATH_IN_CONTAINER} {main_class} "
        f"--config {actor['config_abs_path_in_container']} "
        f"> {LOGS_DIR_IN_CONTAINER}/{actor['name']}.console.log 2>&1"
    )
    subprocess.run(["docker", "exec", "-d", CONTAINER_NAME, "bash", "-c", java_cmd], check=True)


def docker_actor_commands(actor):
    """Match must be anchored to the start of the command (after stripping the PID column), not a
    bare substring search -- PID 1 is docker-init/tini, and `ps` shows its own argv as the entire
    wrapped shell script text (every actor's invocation concatenated together), which trivially
    contains any single actor's pattern as a substring. A plain grep -F would match PID 1 first
    and kill the whole container instead of the intended single actor. Uses `ps` rather than `jps`
    (see router_cpp.py's matching helper) - the runtime image ships no JDK, only a JRE, so `jps`
    isn't available."""
    main_class = MAIN_CLASS_BY_TYPE[actor["type"]]
    pattern = f"{main_class} --config {actor['config_abs_path_in_container']}"
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

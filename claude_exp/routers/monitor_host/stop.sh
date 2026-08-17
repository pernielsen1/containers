#!/usr/bin/env bash
# Stops the monitor_host container for one target. POSTs /stop first (best-effort, lets it tear
# down any actors it Popen'd for itself) then force-removes the container by name -- a container
# name is exact-match by construction, unlike the old per-language monitor_stop.sh scripts' `pgrep
# -f` pattern matching, which had already bitten this project once (see router_java/monitor_stop.sh).
set -euo pipefail

TARGET="${1:-}"
PORT="${2:-8090}"

case "$TARGET" in
  router_py|router_java|router_cpp) ;;
  *)
    echo "Usage: $0 <router_py|router_java|router_cpp> [port]" >&2
    exit 1
    ;;
esac

NAME="monitor_${TARGET}"

curl -s -X POST "http://127.0.0.1:$PORT/stop" >/dev/null 2>&1 || true

if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
    docker rm -f "$NAME" >/dev/null
fi

echo "$NAME stopped"

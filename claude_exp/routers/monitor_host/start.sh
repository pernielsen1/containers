#!/usr/bin/env bash
# Builds monitor_host's image (if needed) and runs it against one target: router_py, router_java,
# or router_cpp. --network host + a docker.sock mount + a bind-mount of the whole routers/ tree
# keep this behaving exactly like the three host-run monitor.py processes it replaces (see
# monitor_host/main.py's module docstring for the full contract).
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

cd "$(dirname "${BASH_SOURCE[0]}")"
REPO_ROOT="$(cd .. && pwd)"
NAME="monitor_${TARGET}"

if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
    echo "$NAME already exists -- stop it first with ./stop.sh $TARGET" >&2
    exit 1
fi

echo "Building monitor_host image..."
docker build -t monitor_host .

echo "Starting $NAME on port $PORT..."
docker run -d --name "$NAME" \
    --network host \
    --init \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$REPO_ROOT":/src \
    -e MONITOR_TARGET="$TARGET" \
    monitor_host --target "$TARGET" --port "$PORT"

echo "Waiting for the dashboard (localhost:$PORT)..."
for i in $(seq 1 30); do
    if curl -sf "http://localhost:$PORT/api/actors" >/dev/null 2>&1; then
        echo "Dashboard up at http://localhost:$PORT"
        exit 0
    fi
    sleep 1
done

echo "Dashboard did not become ready within 30s -- check: docker logs $NAME" >&2
exit 1

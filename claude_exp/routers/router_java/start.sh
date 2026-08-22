#!/usr/bin/env bash
# Builds the router_java image (if needed) and starts the router + crypto_host stack via
# docker-compose. Deploy-style container, same pattern as router_py's/router_cpp's start.sh:
# network_mode host, config bind-mounted, actors are the container's own command (not launched via
# `docker exec` at startup - individual actors can still be restarted that way afterward, see
# ../monitor_host/backends/router_java.py).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

./dockerstart.sh

echo "Building and starting router_java..."
docker compose up -d --build

echo "Waiting for the router's command API (localhost:8080)..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8080/stats >/dev/null 2>&1; then
        echo "router_java is up."
        exit 0
    fi
    sleep 1
done

echo "Router did not become ready within 30s -- check: docker compose logs" >&2
exit 1

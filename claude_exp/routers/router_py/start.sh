#!/usr/bin/env bash
# Builds the router_py image (if needed) and starts the router + crypto_host + downstream_host +
# upstream_host stack via docker-compose. Deploy-style container, same pattern as router_cpp's
# start.sh: network_mode host, project directory bind-mounted, actors are the container's own
# command (not launched via `docker exec`).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "Building and starting router_py..."
docker compose up -d --build

echo "Waiting for the router's command API (localhost:8080)..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8080/stats >/dev/null 2>&1; then
        echo "router_py is up."
        exit 0
    fi
    sleep 1
done

echo "Router did not become ready within 30s -- check: docker compose logs" >&2
exit 1

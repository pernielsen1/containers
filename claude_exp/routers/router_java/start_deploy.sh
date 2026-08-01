#!/usr/bin/env bash
# Builds and starts router_java's *deploy-style* container via docker-compose: the four actors are
# the container's own command (built + launched in-container), not `docker exec -d` into a
# separate long-lived dev container. Same pattern as router_py's and router_cpp's start.sh -- network_mode
# host, project directory bind-mounted, launch mechanism identical across all three
# implementations. This is the container stress testing runs against.
#
# The interactive dev-container flow (./start.sh, ./stop.sh, run_test.sh's `docker exec -d`
# launches into the "router_java" container) is unchanged and still the right tool for day-to-day
# development -- this is a separate, additional container ("router_java-deploy") so the two don't
# collide; do not run both at once (they bind the same ports).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "Building and starting router_java-deploy..."
docker compose up -d --build

echo "Waiting for the router's command API (localhost:8080)..."
for i in $(seq 1 60); do
    if curl -sf http://localhost:8080/stats >/dev/null 2>&1; then
        echo "router_java-deploy is up."
        exit 0
    fi
    sleep 1
done

echo "Router did not become ready within 60s -- check: docker compose logs" >&2
exit 1

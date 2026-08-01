#!/bin/bash
# Stops and removes the router_java dev container. Does not touch the Docker daemon itself.
set -euo pipefail

docker stop router_java 2>/dev/null || true
docker rm router_java 2>/dev/null || true
echo "router_java container stopped and removed."

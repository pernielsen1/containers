#!/bin/bash
# Stops and removes the xv6java dev container. Does not touch the Docker daemon itself.
set -euo pipefail

docker stop xv6java 2>/dev/null || true
docker rm xv6java 2>/dev/null || true
echo "xv6java container stopped and removed."

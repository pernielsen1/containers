#!/usr/bin/env bash
# Stops and removes the router_py container started by start.sh.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

docker compose down

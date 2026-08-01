#!/usr/bin/env bash
# Stops and removes the router_java-deploy container started by start_deploy.sh.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

docker compose down

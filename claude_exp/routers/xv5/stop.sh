#!/usr/bin/env bash
# Stops and removes the xv5 container started by start.sh.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

docker compose down

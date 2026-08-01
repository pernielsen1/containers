#!/usr/bin/env bash
# Stops and removes the shared crypto_host container.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

docker compose down

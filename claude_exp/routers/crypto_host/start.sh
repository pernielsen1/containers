#!/usr/bin/env bash
# Builds the crypto_host image (if needed) and starts the shared crypto_host container via
# docker-compose. Unlike router_py/router_java/router_cpp, this is shared infrastructure, not one of the three
# implementations under comparison - it's meant to stay running across all of their perf runs
# rather than being torn down between them, so re-running this is a harmless no-op if it's
# already up.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "Building and starting crypto_host..."
docker compose up -d --build

echo "Waiting for crypto_host's command API (localhost:8099)..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8099/stats >/dev/null 2>&1; then
        echo "crypto_host is up."
        exit 0
    fi
    sleep 1
done

echo "crypto_host did not become ready within 30s -- check: docker compose logs" >&2
exit 1

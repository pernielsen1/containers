#!/usr/bin/env bash
# Delegates to the shared monitor_host/ container (see monitor_host/main.py's docstring) - the
# per-language monitor/main.py copy this used to run is retired. Runs against the running stack
# the same way: --network host on both this and the router_cpp service means the container's
# command ports (8080-8083) are reachable at localhost directly.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
exec ../monitor_host/start.sh router_cpp "$@"

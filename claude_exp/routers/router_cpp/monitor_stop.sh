#!/usr/bin/env bash
# Delegates to the shared monitor_host/ container's stop.sh. router_cpp/monitor.sh used to run
# the dashboard in the foreground (Ctrl+C to stop) with no separate stop script; now that it's a
# container, it needs one like router_java's/router_py's.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
exec ../monitor_host/stop.sh router_cpp "$@"

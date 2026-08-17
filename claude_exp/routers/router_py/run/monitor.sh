#!/bin/bash
# Delegates to the shared monitor_host/ container (see monitor_host/main.py's docstring) - the
# per-language monitor/main.py copy this used to `exec` is retired.
cd "$(dirname "$0")/.."
exec ../monitor_host/start.sh router_py "$@"

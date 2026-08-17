#!/bin/bash
# Delegates to the shared monitor_host/ container (see monitor_host/main.py's docstring) - the
# per-language monitor/main.py copy this used to `exec` is retired. Requires the router_java
# container to already be running (./start.sh) since actors are launched into it via
# `docker exec -d`, same as before.
cd "$(dirname "$0")"
exec ../monitor_host/start.sh router_java "$@"

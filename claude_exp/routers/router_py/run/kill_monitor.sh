#!/bin/bash
# Delegates to the shared monitor_host/ container's stop.sh - see monitor_host/stop.sh for why
# a docker container name replaced this script's old pidfile-based kill.
cd "$(dirname "$0")/.."
exec ../monitor_host/stop.sh router_py "$@"

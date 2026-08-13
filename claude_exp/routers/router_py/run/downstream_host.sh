#!/bin/bash
cd "$(dirname "$0")/.."
# downstream_host is the shared routers/downstream_host component now, not router_py-local.
exec python3 ../downstream_host/main.py --config simulators/downstream_host/config.json

#!/bin/bash
cd "$(dirname "$0")/.."
# upstream_1 is the shared routers/upstream_host component now, not router_py-local.
exec python3 ../upstream_host/main.py --config ../upstream_host/config.json

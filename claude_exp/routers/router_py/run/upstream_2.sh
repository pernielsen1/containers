#!/bin/bash
cd "$(dirname "$0")/.."
# Binary is the shared routers/upstream_host component now; config stays router_py-local (this
# multi-router test scenario isn't shared with router_java/router_cpp).
exec python3 ../upstream_host/main.py --config simulators/upstream_2/config.json

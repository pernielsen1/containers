#!/bin/bash
cd "$(dirname "$0")/.."
exec python3 router/main.py --config router/router_2/config.json "$@"

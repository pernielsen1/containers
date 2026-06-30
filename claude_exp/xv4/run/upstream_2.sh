#!/bin/bash
cd "$(dirname "$0")/.."
exec python3 simulators/upstream_host/main.py --config simulators/upstream_2/config.json "$@"

#!/usr/bin/env bash
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec python3 simulators/upstream_host/main.py "$@"

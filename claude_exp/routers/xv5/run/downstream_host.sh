#!/bin/bash
cd "$(dirname "$0")/.."
exec python3 simulators/downstream_host/main.py

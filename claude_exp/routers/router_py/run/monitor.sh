#!/bin/bash
cd "$(dirname "$0")/.."
echo $$ > run/.monitor.pid
exec python3 monitor/main.py --port 8090

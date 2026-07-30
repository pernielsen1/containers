#!/usr/bin/env bash
# Runs the xv7cpp dashboard (Flask app, http://localhost:8090) against the running stack. Runs on
# the host, not in the container -- network_mode: host on the xv7cpp service means the
# container's command ports (8080-8083) are reachable at localhost directly.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

python3 -c "import requests, flask" 2>/dev/null || {
    echo "Missing dependency: requests and/or flask. Install with: pip install requests flask" >&2
    exit 1
}

echo "Dashboard starting at http://localhost:8090 -- Ctrl+C to stop."
python3 monitor/main.py

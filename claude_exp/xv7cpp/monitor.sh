#!/usr/bin/env bash
# Runs the Python monitor against the running xv7cpp stack. Runs on the host (not in the
# container) -- network_mode: host on the xv7cpp service means the container's command ports
# (8080-8083) are reachable at localhost directly.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

python3 -c "import requests" 2>/dev/null || {
    echo "Missing dependency: requests. Install with: pip install requests" >&2
    exit 1
}

python3 monitor/main.py config/router_1.json

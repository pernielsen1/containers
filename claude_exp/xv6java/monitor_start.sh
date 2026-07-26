#!/bin/bash
# Starts the monitor dashboard on the HOST (not inside the container) - it's a thin HTTP
# proxy/dashboard that talks to actor CommandServers over the network, so nothing about it
# needs to run inside the JVM container. Requires the xv6java container to already be running
# (./start.sh) since actors are launched into it via `docker exec -d`.
cd "$(dirname "$0")"
echo $$ > .monitor.pid
exec python3 monitor/main.py --port 8090

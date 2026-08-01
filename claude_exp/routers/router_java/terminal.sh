#!/bin/bash
# Opens an interactive shell inside the running router_java container - the equivalent of logging
# into the box the Python version's run/*.sh scripts ran directly on the host. Use this to build
# (`mvn -q -DskipTests package`) and launch/stop individual actors by hand, e.g.:
#   java -cp target/router_java.jar com.xv6.router.RouterMain --config config/router_1.json
#   java -cp target/router_java.jar com.xv6.simulators.cryptohost.CryptoHostMain --config config/crypto_host.json
# (there is no monitor.sh yet in this port - the monitor dashboard is a later iteration, see
# briefs/java_container_router.md - so actors are started/stopped by hand or via run_test.sh
# for now, either from here or with `docker exec router_java ...` directly.)
set -euo pipefail

if ! docker ps --format '{{.Names}}' | grep -qx router_java; then
  echo "router_java container isn't running. Start it first with ./start.sh" >&2
  exit 1
fi

exec docker exec -it router_java bash

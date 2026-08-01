#!/usr/bin/env bash
# Convenience entrypoint: launches the web monitor (http://localhost:8090) for whichever router
# implementation's stack is currently running. The three implementations are mutually exclusive
# (same host ports), so this takes the implementation name and delegates to that implementation's
# own monitor launcher rather than re-implementing the (slightly different) lifecycle per impl.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

IMPL="${1:-}"

case "$IMPL" in
  router_py)
    exec ./router_py/run/monitor.sh
    ;;
  router_java)
    exec ./router_java/monitor.sh
    ;;
  router_cpp)
    exec ./router_cpp/monitor.sh
    ;;
  *)
    echo "Usage: $0 <router_py|router_java|router_cpp>" >&2
    exit 1
    ;;
esac

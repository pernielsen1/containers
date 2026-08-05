#!/usr/bin/env bash
set -euo pipefail

SERVER="${SERVER_USER:?SERVER_USER env var must be set}@serverhp.home"
ALL=(py java cpp)

usage() {
    echo "Usage: SERVER_USER=<user> $0 [crypto|py|java|cpp ...]"
    echo "       Omit targets to stop all three routers (crypto_host stopped separately)."
    exit 1
}

stop_container() {
    local name=$1
    echo "[stop] $name on $SERVER"
    ssh "$SERVER" docker rm -f "$name" 2>/dev/null && echo "$name stopped." || echo "$name was not running."
}

targets=("${@:-${ALL[@]}}")
for t in "${targets[@]}"; do
    case $t in
        crypto)      stop_container crypto_host ;;
        py|java|cpp) stop_container "router_$t" ;;
        *) usage ;;
    esac
done

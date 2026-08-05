#!/usr/bin/env bash
set -euo pipefail

SERVER="${SERVER_USER:?SERVER_USER env var must be set}@serverhp.home"
ALL=(py java cpp)

usage() {
    echo "Usage: SERVER_USER=<user> $0 [crypto|py|java|cpp ...]"
    echo "       Omit targets to start all three routers (crypto_host started separately)."
    exit 1
}

start_container() {
    local name=$1
    echo "[start] $name on $SERVER"
    ssh "$SERVER" bash -s <<EOF
docker rm -f $name 2>/dev/null || true
docker run -d --name $name --network host --init $name
echo "$name started."
EOF
}

targets=("${@:-${ALL[@]}}")
for t in "${targets[@]}"; do
    case $t in
        crypto)      start_container crypto_host ;;
        py|java|cpp) start_container "router_$t" ;;
        *) usage ;;
    esac
done

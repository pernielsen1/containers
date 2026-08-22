#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

SERVER="${SERVER_USER:?SERVER_USER env var must be set}@serverhp.home"
ALL=(crypto downstream py java cpp)

usage() {
    echo "Usage: SERVER_USER=<user> $0 [crypto|downstream|py|java|cpp ...]"
    echo "       Omit targets to deploy all five and start the server."
    exit 1
}

push_image() {
    local image="$1"
    echo "[transfer] $image -> $SERVER"
    docker save "$image" | ssh "$SERVER" docker load
    echo "[done] $image"
}

deploy_crypto() {
    echo "=== crypto_host ==="
    docker compose -f crypto_host/docker-compose.yml build
    push_image crypto_host
}

deploy_downstream() {
    echo "=== downstream_host ==="
    docker build -f downstream_host/Dockerfile -t downstream_host .
    push_image downstream_host
}

deploy_py() {
    echo "=== router_py ==="
    docker compose -f router_py/docker-compose.yml build
    push_image router_py
}

deploy_java() {
    echo "=== router_java ==="
    docker build -f router_java/Dockerfile.prod -t router_java router_java/
    push_image router_java
}

deploy_cpp() {
    echo "=== router_cpp ==="
    docker build -f router_cpp/Dockerfile.prod -t router_cpp router_cpp/
    push_image router_cpp
}

targets=("${@:-${ALL[@]}}")
for t in "${targets[@]}"; do
    case $t in
        crypto)     deploy_crypto ;;
        downstream) deploy_downstream ;;
        py)         deploy_py ;;
        java)       deploy_java ;;
        cpp)        deploy_cpp ;;
        *)          usage ;;
    esac
done

echo "All images loaded on $SERVER. Pruning old images/containers/cache..."
# Every deploy transmits a fresh image under the same tag (see push_image) - the previous image
# with that tag becomes dangling the moment the new one loads, and stopped containers/build cache
# pile up the same way over repeated deploys. Prune every time rather than letting serverhp's disk
# fill up silently.
ssh "$SERVER" docker system prune -f

echo "Starting server..."
# downstream_host has no lifecycle of its own (see server_start.sh) - it only starts paired with
# whichever router is requested, so "downstream" alone is build+push-only here, nothing to start.
start_targets=()
for t in "${targets[@]}"; do
    [ "$t" != "downstream" ] && start_targets+=("$t")
done
if [ "${#start_targets[@]}" -gt 0 ]; then
    ./server_start.sh "${start_targets[@]}"
fi

echo "All done."

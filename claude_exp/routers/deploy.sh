#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

SERVER="${SERVER_USER:?SERVER_USER env var must be set}@serverhp.home"
ALL=(crypto py java cpp)

usage() {
    echo "Usage: SERVER_USER=<user> $0 [crypto|py|java|cpp ...]"
    echo "       Omit targets to deploy all four."
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
    docker compose -f router_cpp/docker-compose.yml build
    push_image router_cpp
}

targets=("${@:-${ALL[@]}}")
for t in "${targets[@]}"; do
    case $t in
        crypto) deploy_crypto ;;
        py)     deploy_py ;;
        java)   deploy_java ;;
        cpp)    deploy_cpp ;;
        *)      usage ;;
    esac
done

echo "All done. Images loaded on $SERVER."

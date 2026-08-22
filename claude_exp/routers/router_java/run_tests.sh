#!/usr/bin/env bash
# Runs the router_java JUnit suite (`mvn test`, including RouterFullStackTest, which spawns the
# shared upstream_host/downstream_host Python components as real subprocesses) in a one-shot
# container built from the Dockerfile's `build` stage. There's no persistent dev container to
# `docker exec` into anymore for this (see start.sh/docker-compose.yml) - each run builds and
# discards its own throwaway container instead.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

./dockerstart.sh

docker build --network host --target build -t router_java-build .

docker run --rm --network host \
  -v "$(pwd)/config":/build/config \
  -v "$(dirname "$(pwd)")/upstream_host":/upstream_host:ro \
  -v "$(dirname "$(pwd)")/downstream_host":/downstream_host:ro \
  router_java-build mvn test

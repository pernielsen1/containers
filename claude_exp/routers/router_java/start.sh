#!/bin/bash
# Builds (if needed) and starts the router_java dev container: Java 25 + Maven + Node/Claude Code CLI,
# with the project directory bind-mounted so editing happens on the host (VSCode etc.) while
# build/run/test happens inside the container via `docker exec`.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

./dockerstart.sh

# Sandboxed-session trust files (see Dockerfile for why): copied in only when present, so the
# same Dockerfile builds unmodified on a normal machine where /root/.ccr doesn't exist.
mkdir -p .ccr-optional
[ -f /root/.ccr/ca-bundle.crt ] && cp /root/.ccr/ca-bundle.crt .ccr-optional/ || true
[ -f /root/.ccr/java-truststore.p12 ] && cp /root/.ccr/java-truststore.p12 .ccr-optional/ || true

# --network host: this build environment intercepts container HTTPS traffic via a proxy that's
# only reachable on the host's own loopback (127.0.0.1:38123) - sharing the host network
# namespace is what lets apt/npm/mvn reach it. Harmless outside that kind of sandbox.
docker build --network host -t router_java "$PROJECT_ROOT"

if docker ps -a --format '{{.Names}}' | grep -qx router_java; then
  echo "Removing existing router_java container..."
  docker rm -f router_java >/dev/null
fi

# /upstream_host, /downstream_host: the shared routers/upstream_host and routers/downstream_host
# Python components (see ../divide_and_conquer.md). Not under $PROJECT_ROOT, so they need their
# own bind mounts - RouterFullStackTest.java launches them as subprocesses from these fixed
# container paths.
docker run -d --name router_java --network host \
  -v "$PROJECT_ROOT":/workspace \
  -v "$(dirname "$PROJECT_ROOT")/upstream_host":/upstream_host:ro \
  -v "$(dirname "$PROJECT_ROOT")/downstream_host":/downstream_host:ro \
  -w /workspace \
  router_java tail -f /dev/null

echo "router_java container running. Build with:"
echo "  docker exec router_java mvn -q -DskipTests package"

#!/bin/bash
# Builds (if needed) and starts the xv6java dev container: Java 21 + Maven + Node/Claude Code CLI,
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
docker build --network host -t xv6java "$PROJECT_ROOT"

if docker ps -a --format '{{.Names}}' | grep -qx xv6java; then
  echo "Removing existing xv6java container..."
  docker rm -f xv6java >/dev/null
fi

docker run -d --name xv6java --network host \
  -v "$PROJECT_ROOT":/workspace -w /workspace \
  xv6java tail -f /dev/null

echo "xv6java container running. Build with:"
echo "  docker exec xv6java mvn -q -DskipTests package"

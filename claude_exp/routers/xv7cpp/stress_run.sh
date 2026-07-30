#!/bin/bash
# Stress-test CLI driver: brings up the xv7cpp docker-compose stack via ./start.sh (all four
# actors run as background processes inside one container), uploads the given CSV, calls
# /start?rate=&duration= (upstream_host cycles the CSV rows at the requested rate for the
# requested duration instead of a single pass), waits for the run to finish, then prints exactly
# ONE line to stdout: a semicolon-delimited result row consumed by routers/stress_test.sh. All
# progress/log output goes to stderr. Direct C++-port analog of xv5/stress_run.sh.
#
# Usage:
#   ./stress_run.sh [--manual] <tps> <duration_s> <csv_file>
set -euo pipefail

MANUAL=0
if [ "${1:-}" == "--manual" ]; then
  MANUAL=1
  shift
fi

TPS="${1:-}"
DURATION="${2:-}"
CSV_FILE="${3:-}"
if [ -z "$TPS" ] || [ -z "$DURATION" ] || [ -z "$CSV_FILE" ]; then
  echo "Usage: $0 [--manual] <tps> <duration_s> <csv_file>" >&2
  exit 1
fi
if [ ! -f "$CSV_FILE" ]; then
  echo "CSV file not found: $CSV_FILE" >&2
  exit 1
fi
CSV_FILE="$(cd "$(dirname "$CSV_FILE")" && pwd)/$(basename "$CSV_FILE")"

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

CRYPTO_CMD=8082
DS_CMD=8081
ROUTER_CMD=8080
UPSTREAM_CMD=8083

cleanup() {
  if [ "$MANUAL" -eq 0 ]; then
    ./stop.sh || true
  fi
}
trap cleanup EXIT

wait_for_stats() {
  local port="$1"
  local name="$2"
  for _ in $(seq 1 30); do
    if curl -s -o /dev/null -f "http://127.0.0.1:${port}/stats"; then
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for ${name} (port ${port}) to come up" >&2
  exit 1
}

if [ "$MANUAL" -eq 0 ]; then
  echo "Building and starting the xv7cpp stack..." >&2
  # Redirected to stderr: docker compose's build/up progress writes to stdout, which would
  # otherwise land inside the single result line stress_test.sh captures via command substitution.
  ./start.sh >&2
else
  echo "Manual mode: assuming the stack is already running." >&2
fi

wait_for_stats "$CRYPTO_CMD" "crypto_host"
wait_for_stats "$DS_CMD" "downstream_host"
wait_for_stats "$ROUTER_CMD" "router_1"
wait_for_stats "$UPSTREAM_CMD" "upstream_1"

echo "Uploading CSV: $CSV_FILE" >&2
curl -s -f -X POST "http://127.0.0.1:${UPSTREAM_CMD}/upload" -F "file=@${CSV_FILE}" >/dev/null

echo "Starting stress send (tps=${TPS} duration=${DURATION}s)..." >&2
START_OK=0
for _ in $(seq 1 15); do
  if curl -s -f "http://127.0.0.1:${UPSTREAM_CMD}/start?rate=${TPS}&duration=${DURATION}" >/dev/null; then
    START_OK=1
    break
  fi
  sleep 1
done
if [ "$START_OK" -ne 1 ]; then
  echo "Timed out waiting for upstream_1 to connect to the router" >&2
  exit 1
fi

# Give the send loop the full duration plus a grace window to let in-flight responses land.
GRACE=5
sleep "$(python3 -c "print(${DURATION} + ${GRACE})")"

echo "Fetching /stress_stats..." >&2
curl -s -f "http://127.0.0.1:${UPSTREAM_CMD}/stress_stats" | python3 -c "
import json, sys
s = json.load(sys.stdin)
print(f'xv7cpp;${TPS};${DURATION};{s[\"sent\"]};{s[\"received\"]};{s[\"errors\"]};{s[\"achieved_tps\"]};{s[\"p50_ms\"]};{s[\"p95_ms\"]};{s[\"p99_ms\"]};{s[\"max_ms\"]}')
"

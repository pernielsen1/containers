#!/bin/bash
# End-to-end CLI driver (not Catch2): brings up the router_cpp docker-compose stack (crypto_host,
# downstream_host, router_main run as background processes inside one container - see
# docker-compose.yml's `command` - there is no separate long-lived dev container to `docker exec`
# into, unlike router_java's), then launches upstream_host as a bare host subprocess (the shared
# routers/upstream_host Python component - see ../divide_and_conquer.md - not one of this
# implementation's own binaries anymore), waits for each /stats endpoint to come up, uploads the
# given CSV to upstream_host, calls /start, polls /results until all rows have a response (30s
# deadline), then prints a PAN/RC/auth-code/field-47 report and the router's 30s stats. Direct
# C++-port analog of router_py/run_test.sh and router_java/run_test.sh - same CLI surface and output format.
#
# Usage:
#   ./run_test.sh <csv_file>            ./start.sh, run the test, ./stop.sh
#   ./run_test.sh --manual <csv_file>   skip start.sh/stop.sh; drive an already-running stack
set -euo pipefail

MANUAL=0
if [ "${1:-}" == "--manual" ]; then
  MANUAL=1
  shift
fi

CSV_FILE="${1:-}"
if [ -z "$CSV_FILE" ]; then
  echo "Usage: $0 [--manual] <csv_file>" >&2
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

# upstream_host is the shared routers/upstream_host Python component (see
# ../divide_and_conquer.md) - a host subprocess, not one of the compose stack's four background
# processes anymore. ./stop.sh (compose down) doesn't reach it, so cleanup also stops it via its
# own /stop route.
cleanup() {
  if [ "$MANUAL" -eq 0 ]; then
    curl -s -o /dev/null -X POST "http://127.0.0.1:${UPSTREAM_CMD}/stop" || true
    ./stop.sh || true
  fi
}
trap cleanup EXIT

wait_for_stats() {
  local port="$1"
  local name="$2"
  for _ in $(seq 1 30); do
    # curl -f: a non-2xx response is a nonzero curl exit, not a body for something downstream
    # to choke on - the whole point of a retry loop is tolerating "not ready yet", so a miss
    # here must not surface as anything other than "try again".
    if curl -s -o /dev/null -f "http://127.0.0.1:${port}/stats"; then
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for ${name} (port ${port}) to come up" >&2
  exit 1
}

if [ "$MANUAL" -eq 0 ]; then
  echo "Building and starting the router_cpp stack..."
  ./start.sh

  wait_for_stats "$CRYPTO_CMD" "crypto_host"
  wait_for_stats "$DS_CMD" "downstream_host"
  wait_for_stats "$ROUTER_CMD" "router_1"

  # upstream_1 connects to the router as a client, so it must start after the router is up -
  # matches the STARTUP_ORDER convention used everywhere else (upstream last).
  echo "Launching upstream_1 (shared routers/upstream_host)..."
  python3 "$PROJECT_ROOT/../upstream_host/main.py" --config "$PROJECT_ROOT/../upstream_host/config.json" &
else
  echo "Manual mode: assuming the stack is already running."
fi

wait_for_stats "$CRYPTO_CMD" "crypto_host"
wait_for_stats "$DS_CMD" "downstream_host"
wait_for_stats "$ROUTER_CMD" "router_1"
wait_for_stats "$UPSTREAM_CMD" "upstream_1"

echo "Uploading CSV: $CSV_FILE"
curl -s -f -X POST "http://127.0.0.1:${UPSTREAM_CMD}/upload" -F "file=@${CSV_FILE}" >/dev/null

EXPECTED_ROWS=$(python3 -c "
import csv
with open('${CSV_FILE}', newline='', encoding='utf-8-sig') as f:
    print(sum(1 for _ in csv.DictReader(f, delimiter=';')))
")

echo "Starting send (${EXPECTED_ROWS} rows)..."
# /start returns non-2xx until upstream_1 finishes its TCP handshake with the router - that
# connect race isn't covered by the /stats readiness checks above, so retry briefly.
START_OK=0
for _ in $(seq 1 15); do
  if curl -s -f "http://127.0.0.1:${UPSTREAM_CMD}/start" >/dev/null; then
    START_OK=1
    break
  fi
  sleep 1
done
if [ "$START_OK" -ne 1 ]; then
  echo "Timed out waiting for upstream_1 to connect to the router" >&2
  exit 1
fi

echo "Polling /results (30s deadline)..."
DEADLINE=$(( $(date +%s) + 30 ))
while true; do
  # Guard the assignment: on a transient miss this pipeline can legitimately fail (curl -f
  # non-2xx, or a still-empty /results body), and under `set -e` an unguarded assignment here
  # would kill the whole script on the very first flaky iteration instead of letting the loop
  # retry - see build_router.md's Glue-script safety checklist / Common pitfalls.
  COUNT=$(curl -s -f "http://127.0.0.1:${UPSTREAM_CMD}/results" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))") || COUNT=0
  if [ "$COUNT" -ge "$EXPECTED_ROWS" ]; then
    break
  fi
  if [ "$(date +%s)" -ge "$DEADLINE" ]; then
    echo "Timed out waiting for all ${EXPECTED_ROWS} results (got ${COUNT})" >&2
    break
  fi
  sleep 0.5
done

echo
echo "=== Results ==="
curl -s "http://127.0.0.1:${UPSTREAM_CMD}/results" | python3 -c "
import json, sys
rows = json.load(sys.stdin)
print(f'{\"PAN\":<20} {\"RC\":<4} {\"Auth Code\":<10} {\"Field 47\"}')
for r in rows:
    pan = r.get('2', '')
    rc = r.get('resp_39', '')
    auth = r.get('resp_38', '')
    f47 = r.get('resp_47', '')
    print(f'{pan:<20} {rc:<4} {auth:<10} {f47}')
"

echo
echo "=== Router 30s stats ==="
curl -s "http://127.0.0.1:${ROUTER_CMD}/stats" | python3 -c "
import json, sys
stats = json.load(sys.stdin)
print(f'sent_30s={stats.get(\"sent_30s\")} recv_30s={stats.get(\"recv_30s\")}')
"

#!/bin/bash
# End-to-end CLI driver (not pytest): launches crypto_host/downstream_host/router/upstream_host
# as background processes, waits for each /stats endpoint to come up, uploads the given CSV,
# calls /start, polls /results until all rows have a response (30s deadline), then prints a
# PAN/RC/auth-code/field-47 report and the router's 30s stats.
#
# Usage:
#   ./run_test.sh <csv_file>            spawn all actors, run the test, tear them down
#   ./run_test.sh --manual <csv_file>   skip spawning; drive already-running actors instead
#                                        (used to debug the IMS Connect handshake by hand)
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

PIDS=()

cleanup() {
  if [ "$MANUAL" -eq 0 ]; then
    for pid in "${PIDS[@]:-}"; do
      kill "$pid" 2>/dev/null || true
    done
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
  echo "Launching crypto_host..."
  python3 simulators/crypto_host/main.py &
  PIDS+=("$!")

  echo "Launching downstream_host..."
  python3 simulators/downstream_host/main.py &
  PIDS+=("$!")

  echo "Launching router_1..."
  python3 router/main.py --config router/router_1/config.json &
  PIDS+=("$!")

  echo "Launching upstream_1..."
  python3 simulators/upstream_host/main.py --config simulators/upstream_1/config.json &
  PIDS+=("$!")
else
  echo "Manual mode: assuming actors are already running."
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
# /start returns 503 until upstream_1 finishes its TCP handshake with the router — that
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
  COUNT=$(curl -s "http://127.0.0.1:${UPSTREAM_CMD}/results" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")
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

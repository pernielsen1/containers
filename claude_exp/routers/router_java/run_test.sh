#!/bin/bash
# End-to-end CLI driver (not JUnit): launches crypto_host/router as background `docker exec -d`
# processes inside the router_java container, and downstream_host/upstream_host as bare host
# subprocesses (the shared routers/downstream_host and routers/upstream_host Python components -
# see ../old/divide_and_conquer.md, ../downstream_host/build_router.md and
# ../upstream_host/build_router.md - downstream_host must stay co-located with wherever the
# router itself runs, since the router connects out to it at "localhost:<port>", unlike
# upstream_host which the router listens for and which can run anywhere reachable), waits for
# each /stats endpoint to come up, uploads the given CSV, calls /start, polls /results until all
# rows have a response (30s deadline), then prints a PAN/RC/auth-code/field-47 report and the
# router's 30s stats. Direct Java-port analog of router_py/run_test.sh.
#
# Usage:
#   ./run_test.sh <csv_file>            build the jar, spawn all actors, run the test, tear them down
#   ./run_test.sh --manual <csv_file>   skip spawning; drive already-running actors instead
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

ROUTER_HOST="${ROUTER_HOST:-127.0.0.1}"

CRYPTO_CMD=8082
DS_CMD=8081
ROUTER_CMD=8080
UPSTREAM_CMD=8083

# Teardown goes through each actor's own /stop HTTP route, not a host-side PID kill. This works
# uniformly across the `docker exec -d` actors (crypto_host/router, whose exec client process on
# the host doesn't forward signals to the java process it launched) and the host-side
# downstream_host/upstream_host subprocesses alike, since /stop just sets that actor's own stop_event and
# its process exits on its own. No different in spirit from router_py's kill_monitor.sh, which also
# stops its target via an HTTP POST rather than a raw signal.
cleanup() {
  if [ "$MANUAL" -eq 0 ]; then
    if [ "$ROUTER_HOST" = "127.0.0.1" ]; then
      for port in "$CRYPTO_CMD" "$DS_CMD" "$ROUTER_CMD"; do
        curl -s -o /dev/null -X POST "http://127.0.0.1:${port}/stop" || true
      done
    fi
    curl -s -o /dev/null -X POST "http://127.0.0.1:${UPSTREAM_CMD}/stop" || true
  fi
}
trap cleanup EXIT

wait_for_stats() {
  local port="$1"
  local name="$2"
  local host="${3:-$ROUTER_HOST}"
  for _ in $(seq 1 30); do
    # curl -f: a non-2xx response is a nonzero curl exit, not a body for something downstream
    # to choke on - the whole point of a retry loop is tolerating "not ready yet", so a miss
    # here must not surface as anything other than "try again".
    if curl -s -o /dev/null -f "http://${host}:${port}/stats"; then
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for ${name} (port ${port}) to come up" >&2
  exit 1
}

if [ "$MANUAL" -eq 0 ]; then
  if [ "$ROUTER_HOST" = "127.0.0.1" ]; then
    echo "Building jar..."
    docker exec router_java mvn -q -DskipTests package

    echo "Launching crypto_host..."
    docker exec -d router_java java -cp target/router_java.jar com.router.simulators.cryptohost.CryptoHostMain \
      --config config/crypto_host.json

    echo "Launching downstream_host (shared routers/downstream_host, host-side not docker exec)..."
    python3 "$PROJECT_ROOT/../downstream_host/main.py" --config config/downstream_host.json &

    echo "Launching router_1..."
    docker exec -d router_java java -cp target/router_java.jar com.router.router.RouterMain \
      --config config/router_1.json
  fi

  echo "Launching upstream_1 (shared routers/upstream_host, host-side not docker exec)..."
  python3 "$PROJECT_ROOT/../upstream_host/main.py" --config "$PROJECT_ROOT/../upstream_host/config.json" --router-host "$ROUTER_HOST" &
else
  echo "Manual mode: assuming actors are already running."
fi

wait_for_stats "$CRYPTO_CMD" "crypto_host"
wait_for_stats "$DS_CMD" "downstream_host"
wait_for_stats "$ROUTER_CMD" "router_1"
wait_for_stats "$UPSTREAM_CMD" "upstream_1" "127.0.0.1"

echo "Uploading CSV: $CSV_FILE"
curl -s -f -X POST "http://127.0.0.1:${UPSTREAM_CMD}/upload" -F "file=@${CSV_FILE}" >/dev/null

EXPECTED_ROWS=$(python3 -c "
import csv
with open('${CSV_FILE}', newline='', encoding='utf-8-sig') as f:
    print(sum(1 for _ in csv.DictReader(f, delimiter=';')))
")

echo "Starting send (${EXPECTED_ROWS} rows)..."
# /start returns 503 until upstream_1 finishes its TCP handshake with the router - that connect
# race isn't covered by the /stats readiness checks above, so retry briefly. Dispatcher.start()
# now blocks until every worker/response-worker thread finishes its own crypto.warmup() before
# the router's upstream socket starts accepting (see Dispatcher.java and stress_run.sh's matching
# comment) - worst case ~3.5s/thread * 16 threads (worker_threads=8 + response default 8) here
# too, since router_1.json also runs ssl_active mTLS end to end.
START_OK=0
for _ in $(seq 1 75); do
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
  # retry.
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
curl -s "http://${ROUTER_HOST}:${ROUTER_CMD}/stats" | python3 -c "
import json, sys
stats = json.load(sys.stdin)
print(f'sent_30s={stats.get(\"sent_30s\")} recv_30s={stats.get(\"recv_30s\")}')
"

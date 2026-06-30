#!/bin/bash
set -e
cd "$(dirname "$0")"

MANUAL=false
CSV_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --manual) MANUAL=true; shift ;;
    *) CSV_FILE="$1"; shift ;;
  esac
done

if [ -z "$CSV_FILE" ]; then
  echo "Usage: $0 [--manual] <csv_file>"
  exit 1
fi

MONITOR_PORT=8090
UPSTREAM_NAME="upstream_1"
UPSTREAM_PORT=8083

wait_http() {
  local port=$1
  local path=${2:-stats}
  for i in $(seq 1 30); do
    if curl -s "http://127.0.0.1:$port/$path" > /dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "ERROR: port $port not ready after 30s"
  exit 1
}

if [ "$MANUAL" = false ]; then
  echo "Starting monitor..."
  bash run/monitor.sh &
  MONITOR_PID=$!
  sleep 2
  wait_http $MONITOR_PORT

  echo "Starting all actors..."
  curl -s -X POST "http://127.0.0.1:$MONITOR_PORT/api/start_all"
  sleep 2

  # Wait for upstream connected
  for i in $(seq 1 30); do
    STATUS=$(curl -s "http://127.0.0.1:$UPSTREAM_PORT/stats" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('connections',{}).get('router','false'))" 2>/dev/null)
    if [ "$STATUS" = "True" ]; then break; fi
    sleep 1
  done
fi

echo "Uploading CSV: $CSV_FILE"
curl -s -X POST "http://127.0.0.1:$MONITOR_PORT/api/actor/$UPSTREAM_NAME/upload_path" \
  -H "Content-Type: application/json" \
  -d "{\"path\": \"$CSV_FILE\"}"
echo

echo "Starting test..."
ROWS=$(curl -s "http://127.0.0.1:$MONITOR_PORT/api/actor/$UPSTREAM_NAME/start" | python3 -c "import sys,json; print(json.load(sys.stdin).get('rows',0))")
echo "Sent $ROWS rows"

echo "Polling results..."
for i in $(seq 1 30); do
  RESULTS=$(curl -s "http://127.0.0.1:$MONITOR_PORT/api/actor/$UPSTREAM_NAME/results")
  COUNT=$(echo "$RESULTS" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
  if [ "$COUNT" -ge "$ROWS" ] && [ "$ROWS" -gt 0 ]; then
    break
  fi
  sleep 1
done

echo ""
echo "=== Results ==="
echo "$RESULTS" | python3 -c "
import sys, json
rows = json.load(sys.stdin)
for r in rows:
    pan = r.get('2','?')
    rc = r.get('resp_39','?')
    auth = r.get('resp_38','')
    expected = r.get('expected_39','')
    status = 'OK' if expected == '' or rc == expected else 'FAIL'
    print(f'{status}  PAN={pan}  rc={rc}  auth={auth}  expected={expected}')
"

if [ "$MANUAL" = false ]; then
  echo ""
  echo "Stopping monitor..."
  bash run/kill_monitor.sh || kill $MONITOR_PID 2>/dev/null || true
fi

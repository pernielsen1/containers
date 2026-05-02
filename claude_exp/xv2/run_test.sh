#!/usr/bin/env bash
set -uo pipefail

usage() { echo "Usage: $0 <csv_file>" >&2; exit 1; }
[[ $# -lt 1 ]] && usage

CSV_FILE="$(realpath "$1")"
[[ -f "$CSV_FILE" ]] || { echo "Error: file not found: $1" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CRYPTO_CMD=8082
DS_CMD=8081
ROUTER_CMD=8080
US_CMD=8083

PIDS=()

cleanup() {
    echo ""
    echo "Stopping actors..."
    curl -sf -X POST "http://localhost:$US_CMD/stop"     >/dev/null 2>&1 || true
    curl -sf -X POST "http://localhost:$ROUTER_CMD/stop" >/dev/null 2>&1 || true
    curl -sf -X POST "http://localhost:$DS_CMD/stop"     >/dev/null 2>&1 || true
    curl -sf -X POST "http://localhost:$CRYPTO_CMD/stop" >/dev/null 2>&1 || true
    sleep 0.3
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
}
trap cleanup EXIT INT TERM

wait_for() {
    local url="$1" name="$2" tries=0
    printf "  %-20s" "$name"
    until curl -sf "$url" >/dev/null 2>&1; do
        sleep 0.4
        (( tries++ )) || true
        [[ $tries -gt 37 ]] && { echo "TIMEOUT"; exit 1; }
    done
    echo "ready"
}

cd "$SCRIPT_DIR"

echo "=== Starting actors ==="
python3 simulators/crypto_host/main.py    &  PIDS+=($!)
wait_for "http://localhost:$CRYPTO_CMD/stats" "crypto_host"

python3 simulators/downstream_host/main.py & PIDS+=($!)
wait_for "http://localhost:$DS_CMD/stats" "downstream_host"

python3 router/main.py                     & PIDS+=($!)
wait_for "http://localhost:$ROUTER_CMD/stats" "router"

python3 simulators/upstream_host/main.py   & PIDS+=($!)
wait_for "http://localhost:$US_CMD/stats" "upstream_host"

echo ""
echo "=== Uploading CSV: $(basename "$CSV_FILE") ==="
curl -sf -X POST \
    -F "file=@${CSV_FILE};type=text/csv" \
    "http://localhost:$US_CMD/upload" | python3 -c "
import sys, json
r = json.load(sys.stdin)
print('  status:', r.get('status'))
"

echo ""
echo "=== Starting run ==="
ROWS=$(curl -sf "http://localhost:$US_CMD/start" | python3 -c "
import sys, json
r = json.load(sys.stdin)
print(r.get('rows', 0))
")
echo "  Sending $ROWS messages"

echo ""
echo "=== Waiting for responses ==="
DEADLINE=$(( $(date +%s) + 30 ))
COUNT=0
while [[ $COUNT -lt $ROWS && $(date +%s) -lt $DEADLINE ]]; do
    sleep 0.5
    COUNT=$(curl -sf "http://localhost:$US_CMD/results" | \
        python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
done

if [[ $COUNT -lt $ROWS ]]; then
    echo "  WARNING: timed out — received $COUNT of $ROWS responses"
else
    echo "  All $COUNT responses received"
fi

echo ""
echo "=== Results ==="
RESULTS=$(curl -sf "http://localhost:$US_CMD/results")
REPORT_DATA="$RESULTS" python3 <<'PYEOF'
import os, json

results = json.loads(os.environ["REPORT_DATA"])
if not results:
    print("  No results")
    sys.exit(0)

approved = sum(1 for r in results if r.get("resp_39") == "00")
declined  = sum(1 for r in results if r.get("resp_39") == "01")
print(f"  Total: {len(results)}   Approved: {approved}   Declined: {declined}")
print()
print(f"  {'PAN':<22} {'RC':>4} {'Auth':>8}  Field47")
print("  " + "-" * 72)
for r in sorted(results, key=lambda x: x.get("2", "")):
    pan  = r.get("2",       "?")
    rc   = r.get("resp_39", "?")
    auth = r.get("resp_38", "")
    f47  = r.get("resp_47", "")
    flag = " ✓" if rc == "00" else " ✗"
    print(f"  {pan:<22} {rc:>4} {auth:>8}  {f47}{flag}")
PYEOF

echo ""
echo "=== Router stats (last 30s) ==="
curl -sf "http://localhost:$ROUTER_CMD/stats" | python3 -c "
import sys, json
s = json.load(sys.stdin)
print(f\"  sent={s['sent_30s']}  recv={s['recv_30s']}\")
"
echo ""

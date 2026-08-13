#!/bin/bash
# Stress-test CLI driver: spawns downstream_host/router/upstream_host the same way run_test.sh
# does, uploads the given CSV, calls /start?rate=&duration= (upstream_host cycles the CSV rows at
# the requested rate for the requested duration instead of a single pass), waits for the run to
# finish, then prints exactly ONE line to stdout: a semicolon-delimited result row consumed by
# routers/stress_test.sh. All progress/log output goes to stderr.
#
# Crypto is NOT this implementation's own local stub here - perf runs hit the real OpenSSL-backed
# routers/crypto_host container (shared across all three implementations, so it's the same
# bottleneck for all of them), via router_1/config_perf.json. That container is shared
# infrastructure, started once by routers/stress_test.sh (or manually via
# routers/crypto_host/start.sh) - it is not launched or torn down here.
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

ROUTER_HOST="${ROUTER_HOST:-127.0.0.1}"
REMOTE_SERVER=""
[ "$ROUTER_HOST" != "127.0.0.1" ] && REMOTE_SERVER="${SERVER_USER:?SERVER_USER must be set for remote stress}@serverhp.home"

CRYPTO_CMD=8099  # shared crypto_host (local port 8099 or remote server port 8099)
DS_CMD=8081
ROUTER_CMD=8080
UPSTREAM_CMD=8083

PIDS=()

cleanup() {
  if [ "$MANUAL" -eq 0 ]; then
    for pid in "${PIDS[@]:-}"; do
      kill "$pid" 2>/dev/null || true
    done
    [ -n "$REMOTE_SERVER" ] && ssh "$REMOTE_SERVER" "docker rm -f router_py 2>/dev/null" >&2 || true
  fi
}
trap cleanup EXIT

wait_for_stats() {
  local port="$1"
  local name="$2"
  local host="${3:-$ROUTER_HOST}"
  for _ in $(seq 1 30); do
    if curl -s -o /dev/null -f "http://${host}:${port}/stats"; then
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for ${name} (port ${port}) to come up" >&2
  exit 1
}

if [ "$MANUAL" -eq 0 ]; then
  # Redirected to stderr, not just left to inherit fd 1: Flask's werkzeug dev server prints its
  # "* Serving Flask app" banner directly to stdout, which would otherwise land inside the single
  # result line stress_test.sh captures via command substitution.
  if [ "$ROUTER_HOST" = "127.0.0.1" ]; then
    echo "Launching downstream_host..." >&2
    python3 ../downstream_host/main.py --config simulators/downstream_host/config_perf.json >&2 &
    PIDS+=("$!")

    echo "Launching router_1 (perf config -> shared crypto_host)..." >&2
    python3 router/main.py --config router/router_1/config_perf.json >&2 &
    PIDS+=("$!")
  else
    echo "Starting router_py on $ROUTER_HOST (perf config, no embedded crypto)..." >&2
    ssh "$REMOTE_SERVER" bash -s >&2 <<'SSH_EOF'
docker rm -f router_py 2>/dev/null || true
docker run -d --name router_py --network host --init router_py bash -c "
  python3 ../downstream_host/main.py --config simulators/downstream_host/config_perf.json >&2 &
  python3 router/main.py --config router/router_1/config_perf.json >&2 &
  sleep infinity"
SSH_EOF
  fi

  echo "Launching upstream_1 (shared routers/upstream_host)..." >&2
  python3 "$PROJECT_ROOT/../upstream_host/main.py" --config "$PROJECT_ROOT/../upstream_host/config_perf.json" --router-host "$ROUTER_HOST" >&2 &
  PIDS+=("$!")
else
  echo "Manual mode: assuming actors are already running." >&2
fi

wait_for_stats "$CRYPTO_CMD" "crypto_host"
wait_for_stats "$DS_CMD" "downstream_host"
wait_for_stats "$ROUTER_CMD" "router_1"
wait_for_stats "$UPSTREAM_CMD" "upstream_1" "127.0.0.1"

echo "Uploading CSV: $CSV_FILE" >&2
curl -s -f -X POST "http://127.0.0.1:${UPSTREAM_CMD}/upload" -F "file=@${CSV_FILE}" >/dev/null

echo "Starting stress send (tps=${TPS} duration=${DURATION}s)..." >&2
# /start returns 503 until upstream_1 finishes its TCP handshake with the router - that connect
# race isn't covered by the /stats readiness checks above, so retry briefly.
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
print(f'router_py;${TPS};${DURATION};{s[\"sent\"]};{s[\"received\"]};{s[\"errors\"]};{s[\"achieved_tps\"]};{s[\"p50_ms\"]};{s[\"p90_ms\"]};{s[\"p95_ms\"]};{s[\"p99_ms\"]};{s[\"max_ms\"]}')
"

# Records the 10 slowest 0100->0110 round trips (send-offset-since-run-start + turnaround time)
# to routers/csv_results/slow_responds.csv - lets a slow response be correlated with *when* in a
# long run it happened (e.g. a GC pause partway through a multi-minute soak test).
mkdir -p "$PROJECT_ROOT/../csv_results"
SLOW_CSV="$PROJECT_ROOT/../csv_results/slow_responds.csv"
if [ ! -f "$SLOW_CSV" ]; then
  echo "timestamp;implementation;target_tps;duration_s;rank;sent_offset_s;latency_ms" > "$SLOW_CSV"
fi
echo "Fetching /slow_responses..." >&2
RUN_TS="$(date -Iseconds)"
curl -s -f "http://127.0.0.1:${UPSTREAM_CMD}/slow_responses?n=10" | python3 -c "
import json, sys
rows = json.load(sys.stdin)
for i, r in enumerate(rows, 1):
    print(f'${RUN_TS};router_py;${TPS};${DURATION};{i};{r[\"sent_offset_s\"]};{r[\"latency_ms\"]}')
" >> "$SLOW_CSV"

# Time-bucketed p50 (30s windows by default) - tells a smooth queueing-backlog ramp apart from
# scattered GC-pause spikes, which a top-10-slowest list alone can't distinguish.
BUCKETS_CSV="$PROJECT_ROOT/../csv_results/latency_buckets.csv"
if [ ! -f "$BUCKETS_CSV" ]; then
  echo "timestamp;implementation;target_tps;duration_s;bucket_start_s;count;p50_ms;max_ms" > "$BUCKETS_CSV"
fi
echo "Fetching /latency_buckets..." >&2
curl -s -f "http://127.0.0.1:${UPSTREAM_CMD}/latency_buckets?bucket_s=30" | python3 -c "
import json, sys
rows = json.load(sys.stdin)
for r in rows:
    print(f'${RUN_TS};router_py;${TPS};${DURATION};{r[\"bucket_start_s\"]};{r[\"count\"]};{r[\"p50_ms\"]};{r[\"max_ms\"]}')
" >> "$BUCKETS_CSV"

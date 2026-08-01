#!/bin/bash
# Top-level stress-testing orchestrator: sweeps a list of target TPS values across all three
# router implementations (router_py, router_java, router_cpp), one implementation at a time - they're mutually
# exclusive, all binding the same host ports (8080-8083). For each (implementation, tps)
# combination, shells out to that implementation's own stress_run.sh, which owns the actual
# build/start/upload/stop lifecycle (raw python processes for router_py, docker exec for router_java,
# docker-compose for router_cpp - genuinely different per port, so that lifecycle logic stays local
# to each implementation rather than being re-derived here). Appends one CSV row per run to
# routers/stress_results.csv, flushing after every run so a partial/aborted sweep still leaves
# usable data.
#
# Crypto validation is a fourth constant across the whole sweep: routers/crypto_host (real
# OpenSSL-backed, shared) is started once below and stays up for every implementation's run, so
# all three are measured against the identical crypto bottleneck instead of their own local stubs.
#
# Usage:
#   ./stress_test.sh [--tps 50,100,200,400] [--duration 30] [--csv <path>] [--impl router_py,router_java,router_cpp]
set -euo pipefail

TPS_LIST="50,100,200,400"
DURATION=30
CSV_FILE=""
IMPL_LIST="router_py,router_java,router_cpp"

while [ $# -gt 0 ]; do
  case "$1" in
    --tps) TPS_LIST="$2"; shift 2 ;;
    --duration) DURATION="$2"; shift 2 ;;
    --csv) CSV_FILE="$2"; shift 2 ;;
    --impl) IMPL_LIST="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

if [ -z "$CSV_FILE" ]; then
  CSV_FILE="$PROJECT_ROOT/router_py/test_csv_files/test.csv"
fi
if [ ! -f "$CSV_FILE" ]; then
  echo "CSV file not found: $CSV_FILE" >&2
  exit 1
fi
CSV_FILE="$(cd "$(dirname "$CSV_FILE")" && pwd)/$(basename "$CSV_FILE")"

RESULTS_CSV="$PROJECT_ROOT/stress_results.csv"
if [ ! -f "$RESULTS_CSV" ]; then
  echo "timestamp;implementation;target_tps;duration_s;sent;received;errors;achieved_tps;p50_ms;p95_ms;p99_ms;max_ms" > "$RESULTS_CSV"
fi

# The shared crypto_host container (real OpenSSL-backed crypto) is started once, here, and stays
# up for the whole sweep - unlike the router implementations it's not mutually exclusive infra,
# it's the constant every implementation is measured against. Each implementation's stress_run.sh
# expects it already running rather than starting/stopping it themselves.
echo "Ensuring shared crypto_host is up..." >&2
"$PROJECT_ROOT/crypto_host/start.sh" >&2

IFS=',' read -ra IMPLS <<< "$IMPL_LIST"
IFS=',' read -ra TPS_VALUES <<< "$TPS_LIST"

# The three implementations share host ports 8080-8083 (network_mode: host / direct bind), but a
# stopped actor doesn't necessarily release its port the instant its own stress_run.sh's teardown
# returns (a POST /stop, a docker exec kill, or a `docker compose down` can all return slightly
# before the OS has actually freed the socket). Starting the next implementation before that
# happens fails its own readiness wait with a confusing "timed out" rather than a port-in-use
# error. Poll for all four ports to go quiet before starting each run.
wait_for_ports_free() {
  for _ in $(seq 1 20); do
    local busy=0
    for port in 8080 8081 8082 8083; do
      if (exec 3<>"/dev/tcp/127.0.0.1/${port}") 2>/dev/null; then
        exec 3<&- 3>&-
        busy=1
      fi
    done
    if [ "$busy" -eq 0 ]; then
      return 0
    fi
    sleep 1
  done
  echo "Warning: ports still busy after waiting - starting next run anyway" >&2
}

for impl in "${IMPLS[@]}"; do
  if [ ! -x "$PROJECT_ROOT/$impl/stress_run.sh" ]; then
    echo "Skipping unknown implementation: $impl" >&2
    continue
  fi
  for tps in "${TPS_VALUES[@]}"; do
    echo "=== $impl @ ${tps} tps for ${DURATION}s ===" >&2
    wait_for_ports_free
    # A single bad run (e.g. one implementation saturating hard enough to fail readiness) must
    # not kill the rest of the sweep - `|| true` lets the loop continue to the next combination.
    ROW=$("$PROJECT_ROOT/$impl/stress_run.sh" "$tps" "$DURATION" "$CSV_FILE") || {
      echo "Run failed for $impl @ ${tps} tps - skipping, continuing sweep" >&2
      continue
    }
    echo "$(date -Iseconds);${ROW}" >> "$RESULTS_CSV"
    echo "  -> ${ROW}" >&2
  done
done

echo "Results written to: $RESULTS_CSV" >&2

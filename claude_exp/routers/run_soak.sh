#!/bin/bash
# One-off soak-test sequence: runs three passes (router_py @ 100 tps, router_java @ 100 tps,
# router_cpp @ 100 tps), each for <number_of_minutes> minutes, with an idle cooldown between
# each phase equal to number_of_minutes / 5. Meant to be run standalone (close the IDE / other
# heavy processes first - this host only has ~2.8GB RAM and a long back-to-back run needs the
# headroom) rather than through Claude Code.
#
# router_java's 100 tps rate no longer needs a preceding validation pass - confirmed clean (0
# errors) at 100 tps/600s directly, so the earlier 5-minute 100-vs-80 tps validation phase this
# script used to run first has been removed.
#
# Usage: ./run_soak.sh [number_of_minutes]
#   number_of_minutes: duration of each phase, in minutes (default 10). Cooldown between phases
#   is number_of_minutes / 5 minutes.
# Prerequisite: routers/crypto_host must already be running (./crypto_host/start.sh if not -
# idempotent, no-ops if already up).
set -uo pipefail

ROUTERS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROUTER_HOST="${ROUTER_HOST:-127.0.0.1}"
# Which physical machine this run happened on (dev laptop / other laptop / serverhp.home) - lets
# csv_results rows be compared/filtered by environment. Override with ENV_NAME if $(hostname)
# isn't a meaningful name for a given host.
ENV_NAME="${ENV_NAME:-$(hostname)}"
# Master copy at the repo root, not any implementation's local test_csv_files/ - those are
# per-implementation mirrors (see sync_test_csv.sh) for that implementation's own local
# convenience only, not the source of truth for stress/soak runs.
CSV_FILE="$ROUTERS_ROOT/test_csv_files/test.csv"

NUM_MINUTES="${1:-10}"
DURATION_S=$(python3 -c "print(int(${NUM_MINUTES} * 60))")
COOLDOWN_S=$(python3 -c "print(${NUM_MINUTES} * 60 / 5)")

# Per-phase results (full row) and a p50/p90/p99-only summary, both semicolon-separated with a
# comma decimal point (European convention, matches every other CSV this user works with) and a
# utf-8-sig BOM so they open cleanly in Excel.
mkdir -p "$ROUTERS_ROOT/csv_results"
SOAK_RESULTS_CSV="$ROUTERS_ROOT/csv_results/soak_results.csv"
SOAK_SUMMARY_CSV="$ROUTERS_ROOT/csv_results/soak_summary.csv"
if [ ! -f "$SOAK_RESULTS_CSV" ]; then
  printf '\xEF\xBB\xBF%s\n' "timestamp;env;implementation;target_tps;duration_s;sent;received;errors;achieved_tps;p50_ms;p90_ms;p95_ms;p99_ms;max_ms" > "$SOAK_RESULTS_CSV"
fi
if [ ! -f "$SOAK_SUMMARY_CSV" ]; then
  printf '\xEF\xBB\xBF%s\n' "timestamp;env;implementation;target_tps;duration_s;p50_ms;p90_ms;p99_ms" > "$SOAK_SUMMARY_CSV"
fi

wait_for_ports_free() {
  [ "$ROUTER_HOST" != "127.0.0.1" ] && return 0
  for _ in $(seq 1 20); do
    local busy=0
    local busy_ports=""
    for port in 8080 8081 8082 8083; do
      if (exec 3<>"/dev/tcp/127.0.0.1/${port}") 2>/dev/null; then
        exec 3<&- 3>&-
        busy=1
        busy_ports="${busy_ports} ${port}"
      fi
    done
    if [ "$busy" -eq 0 ]; then return 0; fi
    sleep 1
  done
  # Used to warn and continue anyway - but starting the next phase with a port still held
  # (e.g. the previous implementation's downstream_host slow to release it under load) guarantees
  # that phase's own actor loses its bind() and dies immediately, which then surfaces as a
  # confusing "port never came up" timeout further downstream instead of this clear cause.
  echo "ERROR: ports still busy after 20s -${busy_ports} - aborting rather than starting the next phase into a guaranteed bind() collision" >&2
  exit 1
}

# Row from stress_run.sh is dot-decimal (python f-string formatting); comma-decimal versions for
# the CSV outputs are produced with a plain ${var//./,} substitution - safe here since the row's
# only other characters are the implementation name and integer fields, neither of which contain
# a literal '.'.
record_result() {
  local row="$1"
  local ts
  ts="$(date -Iseconds)"
  echo "${ts};${ENV_NAME};${row//./,}" >> "$SOAK_RESULTS_CSV"

  local impl tps dur sent recv err atps p50 p90 p95 p99 mx
  IFS=';' read -r impl tps dur sent recv err atps p50 p90 p95 p99 mx <<< "$row"
  echo "${ts};${ENV_NAME};${impl};${tps};${dur};${p50//./,};${p90//./,};${p99//./,}" >> "$SOAK_SUMMARY_CSV"
}

run_phase() {
  local label="$1" dir="$2" tps="$3"
  echo "=== ${label}: ${dir} @ ${tps} tps / ${DURATION_S}s (${NUM_MINUTES} min) ==="
  date -Iseconds
  wait_for_ports_free
  cd "$ROUTERS_ROOT/$dir" || exit 1
  local row
  row=$(./stress_run.sh "$tps" "$DURATION_S" "$CSV_FILE")
  echo "RESULT: $row"
  record_result "$row"
}

if [ "$ROUTER_HOST" = "127.0.0.1" ] && ! curl -sf http://127.0.0.1:8099/stats >/dev/null; then
  echo "ERROR: shared crypto_host (port 8099) is not responding - start it first:" >&2
  echo "  cd $ROUTERS_ROOT/crypto_host && ./start.sh" >&2
  exit 1
elif [ "$ROUTER_HOST" != "127.0.0.1" ]; then
  echo "Ensuring shared crypto_host is up on $ROUTER_HOST..." >&2
  SERVER_USER="${SERVER_USER:?SERVER_USER must be set for remote soak}" \
    "$ROUTERS_ROOT/server_start.sh" crypto >&2
fi

run_phase "PHASE 1" router_py 100

echo "=== COOLDOWN: ${COOLDOWN_S}s idle ==="
date -Iseconds
sleep "$COOLDOWN_S"

run_phase "PHASE 2" router_java 100

echo "=== COOLDOWN: ${COOLDOWN_S}s idle ==="
date -Iseconds
sleep "$COOLDOWN_S"

run_phase "PHASE 3" router_cpp 100

echo "=== ALL PHASES COMPLETE ==="
date -Iseconds
echo "Soak results (full): $SOAK_RESULTS_CSV" >&2
echo "Soak summary (p50/p90/p99): $SOAK_SUMMARY_CSV" >&2

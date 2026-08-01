#!/bin/bash
# One-off soak-test sequence: runs three 10-minute passes (router_py @ 80 tps, router_java @ 100
# tps, router_cpp @ 100 tps), with a 2-minute idle cooldown between each. Meant to be run
# standalone (close the IDE / other heavy processes first - this host only has ~2.8GB RAM and a
# 30+ minute back-to-back run needs the headroom) rather than through Claude Code.
#
# router_java's 100 tps rate no longer needs a preceding validation pass - confirmed clean (0
# errors) at 100 tps/600s directly, so the earlier 5-minute 100-vs-80 tps validation phase this
# script used to run first has been removed.
#
# Usage: ./run_10min_soak_sequence.sh
# Prerequisite: routers/crypto_host must already be running (./crypto_host/start.sh if not -
# idempotent, no-ops if already up).
set -uo pipefail

ROUTERS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSV_REL=test_csv_files/test.csv

wait_for_ports_free() {
  for _ in $(seq 1 20); do
    local busy=0
    for port in 8080 8081 8082 8083; do
      if (exec 3<>"/dev/tcp/127.0.0.1/${port}") 2>/dev/null; then
        exec 3<&- 3>&-
        busy=1
      fi
    done
    if [ "$busy" -eq 0 ]; then return 0; fi
    sleep 1
  done
  echo "Warning: ports still busy after waiting - continuing anyway" >&2
}

if ! curl -sf http://127.0.0.1:8099/stats >/dev/null; then
  echo "ERROR: shared crypto_host (port 8099) is not responding - start it first:" >&2
  echo "  cd $ROUTERS_ROOT/crypto_host && ./start.sh" >&2
  exit 1
fi

echo "=== PHASE 1: router_py @ 80 tps / 600s (10 min) ==="
date -Iseconds
wait_for_ports_free
cd "$ROUTERS_ROOT/router_py" || exit 1
ROW=$(./stress_run.sh 80 600 "$CSV_REL")
echo "RESULT: $ROW"

echo "=== COOLDOWN: 2 minutes idle ==="
date -Iseconds
sleep 120

echo "=== PHASE 2: router_java @ 100 tps / 600s (10 min) ==="
date -Iseconds
wait_for_ports_free
cd "$ROUTERS_ROOT/router_java" || exit 1
ROW=$(./stress_run.sh 100 600 "$CSV_REL")
echo "RESULT: $ROW"

echo "=== COOLDOWN: 2 minutes idle ==="
date -Iseconds
sleep 120

echo "=== PHASE 3: router_cpp @ 100 tps / 600s (10 min) ==="
date -Iseconds
wait_for_ports_free
cd "$ROUTERS_ROOT/router_cpp" || exit 1
ROW=$(./stress_run.sh 100 600 "$CSV_REL")
echo "RESULT: $ROW"

echo "=== ALL PHASES COMPLETE ==="
date -Iseconds

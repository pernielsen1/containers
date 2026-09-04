#!/bin/bash
# C++ port of routers/run_soak_resilience_hard.sh - same before/during/after-kill soak, driving
# router_cpp instead. See router_cpp/soak_resilience_hard.py's own docstring for why this is a
# genuine port (docker-container-hosted router_1, host-launched simulators with explicit perf
# configs) rather than a copy of the root script pointed at a different directory.
#
# Usage: ./run_soak_resilience_hard.sh [number_of_minutes] [--crypto_fail_minutes N] [--comment TEXT]
#   number_of_minutes     total soak duration, in minutes (default 2).
#   --crypto_fail_minutes how long crypto_host stays dead. Default: scaled off number_of_minutes.
#   --comment TEXT         free-text label written to soak_results.csv/soak_summary.csv's comment
#                         column for all three rows this run produces.
# Output: console narration plus THREE rows in routers/csv_results/soak_results.csv +
# soak_summary.csv (implementation="router_cpp_real_crypto_before_kill" / "_during_kill" /
# "_after_kill").
set -uo pipefail

ROUTERS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

NUM_MINUTES=2
CRYPTO_FAIL_MINUTES=""
COMMENT=""
POSITIONAL_SET=0
while [ $# -gt 0 ]; do
  case "$1" in
    --crypto_fail_minutes)
      CRYPTO_FAIL_MINUTES="$2"
      shift 2
      ;;
    --crypto_fail_minutes=*)
      CRYPTO_FAIL_MINUTES="${1#*=}"
      shift
      ;;
    --comment)
      COMMENT="$2"
      shift 2
      ;;
    --comment=*)
      COMMENT="${1#*=}"
      shift
      ;;
    *)
      if [ "$POSITIONAL_SET" -eq 0 ]; then
        NUM_MINUTES="$1"
        POSITIONAL_SET=1
      fi
      shift
      ;;
  esac
done

EXTRA_ARGS=()
if [ -n "$COMMENT" ]; then
  EXTRA_ARGS+=("--comment" "$COMMENT")
fi

echo "run_soak_resilience_hard.sh (router_cpp): ${NUM_MINUTES} min total, crypto_fail_minutes=${CRYPTO_FAIL_MINUTES:-auto}, comment=${COMMENT:-<none>}"
cd "$ROUTERS_ROOT/router_cpp" || exit 1
exec python3 soak_resilience_hard.py "$NUM_MINUTES" "$CRYPTO_FAIL_MINUTES" "${EXTRA_ARGS[@]}"

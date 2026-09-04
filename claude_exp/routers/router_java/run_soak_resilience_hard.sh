#!/bin/bash
# router_java port of ../run_soak_resilience_hard.sh - see soak_resilience_hard.py's own docstring
# for the scenario and the router_java-specific architectural adaptation (router_1 is baked into
# the container's compose command, not a bare host subprocess).
#
# Usage: ./run_soak_resilience_hard.sh [number_of_minutes] [--crypto_fail_minutes N] [--stub-crypto] [--comment TEXT]
#   number_of_minutes     total soak duration, in minutes (default 2).
#   --crypto_fail_minutes how long crypto_host stays dead. Default: scaled off number_of_minutes.
#   --stub-crypto          use router_java's own container-local crypto_host stub instead of the
#                         real, shared container.
#   --comment TEXT         free-text label written to soak_results.csv/soak_summary.csv's comment
#                         column for all three rows this run produces.
# Output: console narration plus THREE rows in routers/csv_results/soak_results.csv +
# soak_summary.csv (implementation="router_java_real_crypto_before_kill" / "_during_kill" /
# "_after_kill" by default, or "router_java_before_kill" / etc. with --stub-crypto).
set -uo pipefail

ROUTERS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

NUM_MINUTES=2
CRYPTO_FAIL_MINUTES=""
STUB_CRYPTO=0
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
    --stub-crypto)
      STUB_CRYPTO=1
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
if [ "$STUB_CRYPTO" -eq 1 ]; then
  EXTRA_ARGS+=("--stub-crypto")
fi
if [ -n "$COMMENT" ]; then
  EXTRA_ARGS+=("--comment" "$COMMENT")
fi

echo "run_soak_resilience_hard.sh (router_java): ${NUM_MINUTES} min total, crypto_fail_minutes=${CRYPTO_FAIL_MINUTES:-auto}, stub_crypto=${STUB_CRYPTO}, comment=${COMMENT:-<none>}"
cd "$ROUTERS_ROOT/router_java" || exit 1
exec python3 soak_resilience_hard.py "$NUM_MINUTES" "$CRYPTO_FAIL_MINUTES" "${EXTRA_ARGS[@]}"

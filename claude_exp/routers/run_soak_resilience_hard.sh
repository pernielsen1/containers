#!/bin/bash
# briefs/resilience_v2.md: "in addition to run_soak.sh" - resilience-flavored soak run. Sustained
# TPS traffic against the full local host-python stack; after a fixed 1 minute, crypto_host is
# hard-killed (a real SIGKILL, not a clean shutdown) and held dead for --crypto_fail_minutes,
# then restarted - all while traffic keeps flowing. Brief: "this will trigger a bunch of 0120 and
# 0420 messages - interesting if we can keep up" - see soak_resilience_hard.py's own docstring
# for why that's actually an open question against what's built, not a given.
#
# router_py only for now, on host (not containerized) - briefs/resilience_v2.md's "experiment
# python only in host" scopes this whole document to host python files first, and this script
# runs the FULL local stack itself (downstream_host, router_1, upstream_1, and router_py's own
# host-mode crypto_host stub), not the shared OpenSSL-backed routers/crypto_host container
# run_soak.sh/stress_run.sh use - so it's safe to run standalone or alongside run_soak.sh.
#
# Usage: ./run_soak_resilience_hard.sh [number_of_minutes] [--crypto_fail_minutes N]
#   number_of_minutes     total soak duration, in minutes (default 10). Must leave room for a
#                         fixed 1-minute before_kill stage + crypto_fail_minutes + a >=30s
#                         after_kill stage.
#   --crypto_fail_minutes how long crypto_host stays dead (default 2)
# Output: console narration plus THREE rows in routers/csv_results/soak_results.csv +
# soak_summary.csv (implementation="router_py_before_kill" / "_during_kill" / "_after_kill").
set -uo pipefail

ROUTERS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

NUM_MINUTES=10
CRYPTO_FAIL_MINUTES=2
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
    *)
      if [ "$POSITIONAL_SET" -eq 0 ]; then
        NUM_MINUTES="$1"
        POSITIONAL_SET=1
      fi
      shift
      ;;
  esac
done

echo "run_soak_resilience_hard.sh: ${NUM_MINUTES} min total, crypto_fail_minutes=${CRYPTO_FAIL_MINUTES}"
cd "$ROUTERS_ROOT/router_py" || exit 1
exec python3 soak_resilience_hard.py "$NUM_MINUTES" "$CRYPTO_FAIL_MINUTES"

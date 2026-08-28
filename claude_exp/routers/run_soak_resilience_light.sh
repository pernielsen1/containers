#!/bin/bash
# briefs/resilience_v2.md: "in addition to run_soak.sh" - resilience-flavored soak run, sustained
# TPS traffic while --fail_percentage of crypto_host's requests (any PAN, any leg) get no
# response at all, verifying the router still sustains 100 TPS via its fire-and-forget response
# leg (router/session.py's short crypto_response_timeout_seconds) rather than stalling.
#
# router_py only for now, on host (not containerized) - briefs/resilience_v2.md's "experiment
# python only in host" scopes this whole document to host python files first, and this script
# runs the FULL local stack itself (downstream_host, router_1, upstream_1, and router_py's own
# host-mode crypto_host stub), not the shared OpenSSL-backed routers/crypto_host container
# run_soak.sh/stress_run.sh use - so it's safe to run standalone or alongside run_soak.sh.
#
# Usage: ./run_soak_resilience_light.sh [number_of_minutes] [--fail_percentage N] [--tps N]
#   number_of_minutes  duration of the sustained-traffic window, in minutes (default 10)
#   --fail_percentage  percent (0-100) of crypto_host requests that get no response (default 10)
#   --tps               target transactions/sec (default 100)
# Output: console narration plus a row in routers/csv_results/soak_results.csv + soak_summary.csv
# (implementation="router_py_fail_pctN", plus "_tpsN" when --tps isn't 100).
set -uo pipefail

ROUTERS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

NUM_MINUTES=10
FAIL_PERCENTAGE=10
TPS=100
POSITIONAL_SET=0
while [ $# -gt 0 ]; do
  case "$1" in
    --fail_percentage)
      FAIL_PERCENTAGE="$2"
      shift 2
      ;;
    --fail_percentage=*)
      FAIL_PERCENTAGE="${1#*=}"
      shift
      ;;
    --tps)
      TPS="$2"
      shift 2
      ;;
    --tps=*)
      TPS="${1#*=}"
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

echo "run_soak_resilience_light.sh: ${NUM_MINUTES} min, fail_percentage=${FAIL_PERCENTAGE}%, tps=${TPS}"
cd "$ROUTERS_ROOT/router_py" || exit 1
exec python3 soak_resilience_light.py "$NUM_MINUTES" "$FAIL_PERCENTAGE" "$TPS"

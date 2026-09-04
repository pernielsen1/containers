#!/bin/bash
# briefs/resilience_v2.md: "in addition to run_soak.sh" - resilience-flavored soak run. Sustained
# TPS traffic against the full local host-python stack; after a before_kill stage, crypto_host is
# hard-killed (a real SIGKILL, not a clean shutdown) and held dead for --crypto_fail_minutes,
# then restarted - all while traffic keeps flowing. The brief's original spec fixed before_kill at
# 1 minute; this now scales with number_of_minutes instead (see soak_resilience_hard.py) so a
# short experimental run isn't sized for a 10-minute soak. Brief: "this will trigger a bunch of
# 0120 and 0420 messages - interesting if we can keep up" - see soak_resilience_hard.py's own
# docstring for why that's actually an open question against what's built, not a given.
#
# router_py only for now, on host (not containerized) - briefs/resilience_v2.md's "experiment
# python only in host" scopes this whole document to host python files first, and this script
# runs the FULL local stack itself (downstream_host, router_1, upstream_1, and - by default - the
# real, shared OpenSSL-backed routers/crypto_host container run_soak.sh/stress_run.sh use, which
# must already be up: crypto_host/start.sh). Pass --stub-crypto to use router_py's own lightweight
# host-mode crypto_host stub instead (starts/kills/restarts it itself, no docker needed) - see
# soak_resilience_hard.py's docstring.
#
# Usage: ./run_soak_resilience_hard.sh [number_of_minutes] [--crypto_fail_minutes N] [--stub-crypto] [--comment TEXT]
#   number_of_minutes     total soak duration, in minutes (default 2 - kept low so experimenting
#                         doesn't carry the overhead of a full soak; before_kill/during_kill/
#                         after_kill stage lengths all scale off this, see soak_resilience_hard.py).
#   --crypto_fail_minutes how long crypto_host stays dead. Default: scaled off number_of_minutes
#                         (see soak_resilience_hard.py) rather than a fixed value - pass this to
#                         pin it explicitly instead (e.g. the brief's real-world 2 minutes).
#   --stub-crypto          use the local Flask crypto_host stub instead of the real container.
#   --comment TEXT         free-text label written to soak_results.csv/soak_summary.csv's comment
#                         column for all three rows this run produces (e.g. "baseline 20260904").
# Output: console narration plus THREE rows in routers/csv_results/soak_results.csv +
# soak_summary.csv (implementation="router_py_real_crypto_before_kill" / "_during_kill" /
# "_after_kill" by default, or "router_py_before_kill" / etc. with --stub-crypto).
set -uo pipefail

ROUTERS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

echo "run_soak_resilience_hard.sh: ${NUM_MINUTES} min total, crypto_fail_minutes=${CRYPTO_FAIL_MINUTES:-auto}, stub_crypto=${STUB_CRYPTO}, comment=${COMMENT:-<none>}"
cd "$ROUTERS_ROOT/router_py" || exit 1
exec python3 soak_resilience_hard.py "$NUM_MINUTES" "$CRYPTO_FAIL_MINUTES" "${EXTRA_ARGS[@]}"

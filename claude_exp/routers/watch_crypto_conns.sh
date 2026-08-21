#!/bin/bash
# Diagnostic for the router_java mid-run step investigation (see big_question.md and
# statistics.md's 2026-08-20 section). fixjava.sh already ruled out a purely JVM-internal cause
# (java run first & alone against a freshly restarted crypto_host showed no step at all). This
# script tests the follow-on theory instead: that crypto_host's connection state is carried
# across phases within a single run_soak.sh invocation (crypto_host is shared infra, never
# restarted between phases - see run_soak.sh's own prerequisite note), and that java's mid-run
# step is java's own connection pool (up to workerThreads + responseWorkerThreads = 16
# concurrent connections, per the Dispatcher note in crypto_host_main.cpp) colliding with
# connections still pinned in crypto_host's fixed 24-thread cpp-httplib pool from the phase
# that ran before it (python, per run_soak.sh's py -> java -> cpp order) - cpp-httplib is
# thread-per-connection and a thread stays pinned for a connection's whole idle lifetime, not
# just active request time, so a connection python's process didn't cleanly close can still be
# occupying a pool thread when java's phase starts.
#
# Polls `ss` for crypto_host's plugin-execution port (5099, not the 8099 command/stats port -
# 5099 is the one behind the 24-thread pool in question) once a second, logging counts by TCP
# state. Run this in its own terminal, started BEFORE run_soak.sh so it's already polling across
# every phase transition. If the pinning theory is right, expect TIME-WAIT/CLOSE-WAIT (or an
# ESTAB count that doesn't drop back near 0) left over right as the python phase ends, and the
# established count creeping toward the ~24 pool ceiling partway into java's phase - roughly
# lining up with the ~60s-in step seen in soak_summary.csv/latency_buckets.csv on 2026-08-20.
#
# Usage: ./watch_crypto_conns.sh [duration_s]
#   duration_s: stop automatically after this many seconds (default: run until Ctrl+C).

set -uo pipefail

ROUTERS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=5099
DURATION_S="${1:-0}"

mkdir -p "$ROUTERS_ROOT/csv_results"
ENV_NAME="${ENV_NAME:-$(hostname)}"
OUT_CSV="$ROUTERS_ROOT/csv_results/crypto_conns.csv"
[ -f "$OUT_CSV" ] || printf '\xEF\xBB\xBF%s\n' "timestamp;env;elapsed_s;established;time_wait;close_wait;other;total" > "$OUT_CSV"

echo "Polling ss for crypto_host plugin port ${PORT} every 1s -> ${OUT_CSV}" >&2
echo "Start run_soak.sh in another terminal now if you haven't already." >&2
[ "$DURATION_S" -gt 0 ] 2>/dev/null && echo "Will auto-stop after ${DURATION_S}s." >&2
echo "Ctrl+C to stop." >&2

START_TS=$(date +%s)
trap 'echo "Stopped." >&2; exit 0' INT TERM

while true; do
  NOW_TS=$(date +%s)
  ELAPSED=$((NOW_TS - START_TS))
  if [ "$DURATION_S" -gt 0 ] && [ "$ELAPSED" -ge "$DURATION_S" ]; then
    echo "Duration ${DURATION_S}s reached, stopping." >&2
    break
  fi

  LINES="$(ss -tn state all "( sport = :${PORT} or dport = :${PORT} )" 2>/dev/null | tail -n +2 | grep -v '^LISTEN')"
  EST=$(printf '%s\n' "$LINES" | grep -c '^ESTAB')
  TW=$(printf '%s\n' "$LINES" | grep -c '^TIME-WAIT')
  CW=$(printf '%s\n' "$LINES" | grep -c '^CLOSE-WAIT')
  TOTAL=$(printf '%s\n' "$LINES" | grep -c '.')
  OTHER=$((TOTAL - EST - TW - CW))

  TS="$(date -Iseconds)"
  echo "${TS};${ENV_NAME};${ELAPSED};${EST};${TW};${CW};${OTHER};${TOTAL}" >> "$OUT_CSV"

  sleep 1
done

echo "crypto_conns.csv: polling stopped, rows appended for this session's window (elapsed 0-${ELAPSED}s)." >&2

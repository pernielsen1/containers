#!/bin/bash
# One-off diagnostic for the router_java investigation (see big_question.md / statistics.md
# "2026-08-20" section): runs router_java FIRST and ALONE, standalone from run_soak.sh, against a
# freshly restarted crypto_host - nothing else touches crypto_host today before this. Tests
# whether the ~60s mid-run latency step (flat ~3-4ms -> flat ~11ms, seen in yesterday's
# comparable 2-minute run) is:
#   (a) JVM-internal (JIT tier-up/deopt, GC generation promotion) - would still appear here,
#       since stress_run.sh already gives router_java a brand-new JVM process every call
#       regardless of phase order, or
#   (b) caused by the shared crypto_host carrying state across phases - would disappear here,
#       since java is normally always phase 2 in run_soak.sh (after python's phase has already
#       run against crypto_host); this run removes that variable entirely.
#
# Deliberately does NOT add an extra pre-measurement warmup pass beyond stress_run.sh's own
# built-in warmup_s (default 10s, just enough to clear TLS handshake / connection-pool fill
# before the measured clock starts - same convention every prior soak/stress number in this repo
# uses). Adding a longer warmup here would push the JVM past the very transition this run exists
# to observe, defeating the point.
#
# Usage: ./fixjava.sh
set -euo pipefail

ROUTERS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSV_FILE="$ROUTERS_ROOT/test_csv_files/test.csv"
TPS=100
DURATION_S=120

mkdir -p "$ROUTERS_ROOT/csv_results"
ENV_NAME="${ENV_NAME:-$(hostname)}"
SOAK_RESULTS_CSV="$ROUTERS_ROOT/csv_results/soak_results.csv"
SOAK_SUMMARY_CSV="$ROUTERS_ROOT/csv_results/soak_summary.csv"
[ -f "$SOAK_RESULTS_CSV" ] || printf '\xEF\xBB\xBF%s\n' "timestamp;env;implementation;target_tps;duration_s;sent;received;errors;achieved_tps;p50_ms;p90_ms;p95_ms;p99_ms;max_ms" > "$SOAK_RESULTS_CSV"
[ -f "$SOAK_SUMMARY_CSV" ] || printf '\xEF\xBB\xBF%s\n' "timestamp;env;implementation;target_tps;duration_s;p50_ms;p90_ms;p99_ms" > "$SOAK_SUMMARY_CSV"

echo "=== Stopping crypto_host and router_java (clean slate) ===" >&2
"$ROUTERS_ROOT/crypto_host/stop.sh" || true
"$ROUTERS_ROOT/router_java/stop.sh" || true

# Belt-and-suspenders: make sure nothing from a previous/crashed run is still holding the ports
# stress_run.sh needs (downstream_host/router/upstream_host are plain host subprocesses, not
# containers, so stop.sh above can't touch them).
for port in 8080 8081 8083; do
  if (exec 3<>"/dev/tcp/127.0.0.1/${port}") 2>/dev/null; then
    exec 3<&- 3>&-
    echo "ERROR: port ${port} still busy after stopping containers - find and kill the stray process first (ss -ltnp | grep ${port})" >&2
    exit 1
  fi
done

echo "=== Starting crypto_host fresh ===" >&2
"$ROUTERS_ROOT/crypto_host/start.sh" >&2

echo "=== Starting router_java container fresh (stress_run.sh launches the actual JVM router process itself, per-call) ===" >&2
"$ROUTERS_ROOT/router_java/start.sh" >&2

echo "=== Measured run: router_java @ ${TPS} tps / ${DURATION_S}s (120s = 2 min), first thing today against this crypto_host ===" >&2
date -Iseconds >&2
cd "$ROUTERS_ROOT/router_java"
ROW="$(./stress_run.sh "$TPS" "$DURATION_S" "$CSV_FILE")"
echo "RESULT: $ROW" >&2
date -Iseconds >&2

TS="$(date -Iseconds)"
echo "${TS};${ENV_NAME};${ROW//./,}" >> "$SOAK_RESULTS_CSV"

IFS=';' read -r impl tps dur sent recv err atps p50 p90 p95 p99 mx <<< "$ROW"
echo "${TS};${ENV_NAME};${impl};${tps};${dur};${p50//./,};${p90//./,};${p99//./,}" >> "$SOAK_SUMMARY_CSV"

echo "=== Done ===" >&2
echo "soak_results.csv / soak_summary.csv: appended one row (timestamp ${TS})" >&2
echo "latency_buckets.csv / slow_responds.csv: stress_run.sh already appended router_java's rows directly - check the 30s buckets there for whether the ~60s step reproduced" >&2

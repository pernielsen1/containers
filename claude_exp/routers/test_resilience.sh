#!/bin/bash
# Top-level resilience-testing orchestrator: runs each router implementation's own
# test_resilience.sh in turn - they're mutually exclusive, all binding the same host ports
# (8080-8083), same constraint as stress_test.sh. Unlike stress_test.sh (a single numeric
# measurement per run, captured from stdout and appended to one shared CSV), each
# implementation's resilience suite is a self-contained narrated scenario run with its own
# <impl>/test_resilience.csv (timestamp;actor;event) - this script just streams that output live
# and moves on to the next implementation, it doesn't aggregate a CSV of its own.
#
# Implementations without a test_resilience.sh yet are skipped, not treated as a failure - as of
# writing only router_py has this suite (see resilience.md); router_java/router_cpp get the same
# treatment stress_test.sh gives an implementation missing stress_run.sh.
#
# Usage:
#   ./test_resilience.sh [--impl router_py,router_java,router_cpp]
set -euo pipefail

IMPL_LIST="router_py,router_java,router_cpp"

while [ $# -gt 0 ]; do
  case "$1" in
    --impl) IMPL_LIST="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

IFS=',' read -ra IMPLS <<< "$IMPL_LIST"

# Same rationale as stress_test.sh: all three implementations share host ports 8080-8083 (network
# mode: host / direct bind), and a stopped actor doesn't necessarily release its port the instant
# the previous suite's teardown returns.
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
  echo "Warning: ports still busy after waiting - starting next suite anyway" >&2
}

ran_any=0
for impl in "${IMPLS[@]}"; do
  if [ ! -x "$PROJECT_ROOT/$impl/test_resilience.sh" ]; then
    echo "Skipping $impl: no test_resilience.sh yet" >&2
    continue
  fi
  echo "=== $impl resilience suite ===" >&2
  wait_for_ports_free
  ran_any=1
  # One implementation's suite failing (or finding a real bug) must not stop the others from
  # running - report and continue, same spirit as stress_test.sh's per-run `|| true` handling.
  if ! "$PROJECT_ROOT/$impl/test_resilience.sh"; then
    echo "$impl resilience suite exited non-zero - see output above" >&2
  fi
  echo "  -> $impl done, log: $PROJECT_ROOT/$impl/test_resilience.csv" >&2
done

if [ "$ran_any" -eq 0 ]; then
  echo "No implementations had a test_resilience.sh to run." >&2
  exit 1
fi

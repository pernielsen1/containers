#!/usr/bin/env bash
# Thin wrapper - the actual orchestration/test cases live in test_resilience.py (per
# resilience.md: "the test suite is orchestrated in python"). See that file's docstring.
# Unlike router_py, every non-upstream_host/downstream_host actor here runs via `docker exec`
# into an already-built-and-running container - start it first with ./start.sh if it isn't up.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
exec python3 test_resilience.py "$@"

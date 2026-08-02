#!/usr/bin/env bash
# Thin wrapper - the actual orchestration/test cases live in test_resilience.py (per
# resilience.md: "the test suite is orchestrated in python"). See that file's docstring.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
exec python3 test_resilience.py "$@"

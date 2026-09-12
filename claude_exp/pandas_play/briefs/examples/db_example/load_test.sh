#!/usr/bin/env bash
# Builds a small, referentially-consistent subset of prod/input into
# test/input (num_test_entries from prod/config.json, FK chain and
# orphan rows preserved -- see build_test_input.py), then loads it via
# load.sh --env test.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 "$HERE/build_test_input.py"
"$HERE/load.sh" --env test

#!/usr/bin/env bash
# Thin wrapper - the actual orchestration lives in chaos_monkey.py. See that file's docstring.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
exec python3 chaos_monkey.py "$@"

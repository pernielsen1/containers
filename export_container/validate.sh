#!/usr/bin/env bash
# validate.sh — run AnaCredit counterparty validation on a CSV file
#
# Runs both validators:
#   1. validate_counterparty.py  — field-level checks (completeness, consistency, postal codes)
#   2. validate_cp_xref.py       — referential integrity (RI0140_DE / RI0150_DE / RI0160_DE)
#
# Usage:
#   ./validate.sh <input.csv> [extra args passed to validate_counterparty.py]
#
# Examples:
#   ./validate.sh sample_counterparty.csv
#   ./validate.sh data/counterparties.csv --summary
#   ./validate.sh data/counterparties.csv --output report.csv --no-warnings

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$SCRIPT_DIR/src"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <input.csv> [--output <report.csv>] [--summary] [--no-warnings]"
    exit 1
fi

INPUT="$1"
shift

if [[ ! -f "$INPUT" ]]; then
    echo "Error: file not found: $INPUT"
    exit 1
fi

cd "$SCRIPT_DIR"

rc=0

echo "=== Field validation (validate_counterparty.py) ==="
python3 "$SRC_DIR/validate_counterparty.py" "$INPUT" "$@" || rc=1

echo ""
echo "=== Cross-reference validation (validate_cp_xref.py) ==="
python3 "$SRC_DIR/validate_cp_xref.py" "$INPUT" || rc=1

exit $rc

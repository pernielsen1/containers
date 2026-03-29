#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAPPED_CSV="$SCRIPT_DIR/bista_report.csv"

echo "=== Step 1: bista_mapper.py (IFRS) ==="
python3 "$SCRIPT_DIR/bista_mapper.py" \
    --standard ifrs \
    --gl "$SCRIPT_DIR/sample_gl_ifrs.csv" \
    --output "$MAPPED_CSV"

echo "=== Step 2: bista_to_xml.py ==="
XML_OUT="$SCRIPT_DIR/bista2603.xml"
python3 "$SCRIPT_DIR/bista_to_xml.py" \
    --csv "$MAPPED_CSV" \
    --period 2026-03 \
    --output "$XML_OUT"

echo "=== Step 3: verify_bista_xml.py ==="
python3 "$SCRIPT_DIR/verify_bista_xml.py" "$XML_OUT"

echo "=== Done ==="

#!/usr/bin/env bash
# Copies test data/fixtures (no code) from xv2 into ../xv3, preserving relative layout.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_DIR="$(cd "$SRC_DIR/.." && pwd)/xv3"

FILES=(
  "test_spec.json"
  "pans_defined.json"
  "f47.json"
  "requirements.txt"
  "test_csv_files/test.csv"
  "test_csv_files/test_crypt.csv"
  "test_csv_files/test_one.csv"
  "test_csv_files/test_two.csv"
  "simulators/upstream_1/input/test_cases.csv"
  "simulators/upstream_2/input/test_cases.csv"
  "simulators/upstream_3/input/test_cases.csv"
  "simulators/upstream_host/input/sample.csv"
  "simulators/upstream_host/input/test_cases.csv"
)

echo "Copying test data from $SRC_DIR to $DEST_DIR"

for rel in "${FILES[@]}"; do
  src="$SRC_DIR/$rel"
  dest="$DEST_DIR/$rel"
  if [[ ! -f "$src" ]]; then
    echo "  SKIP (missing): $rel"
    continue
  fi
  mkdir -p "$(dirname "$dest")"
  cp -v "$src" "$dest"
done

echo "Done."

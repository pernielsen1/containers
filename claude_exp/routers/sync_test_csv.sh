#!/bin/bash
# Mirrors routers/test_csv_files/ (the master) into each implementation's own local
# test_csv_files/ directory. The root master is what stress_test.sh and run_soak.sh read from
# directly; the per-implementation copies exist only for that implementation's own local
# convenience - its own run_test.sh and its monitor UI's CSV dropdown (GET /api/csv_files) both
# read from their local directory, not the root. Re-run this after adding/editing a CSV in the
# root test_csv_files/ to push the change out to all three.
set -euo pipefail

ROUTERS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for impl in router_py router_java router_cpp; do
  mkdir -p "$ROUTERS_ROOT/$impl/test_csv_files"
  cp "$ROUTERS_ROOT"/test_csv_files/*.csv "$ROUTERS_ROOT/$impl/test_csv_files/"
done

echo "Mirrored $(ls "$ROUTERS_ROOT"/test_csv_files/*.csv | wc -l) CSV(s) from routers/test_csv_files/ into router_py/router_java/router_cpp test_csv_files/"

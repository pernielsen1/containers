#!/usr/bin/env bash
# Generates a big sample CSV (if not already there) and loads it into
# SQLite efficiently -- chunked read, one transaction, index built
# after the load. See load_csv.py for the actual technique.
#
# Usage: ./load_csv.sh [n_rows]   (default 300000, only used on first
# generation -- delete big_sample.csv to regenerate with a new count)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_PATH="$HERE/config.json"
N_ROWS="${1:-300000}"

DB_STORAGE_DIR="$(python3 -c "import json; print(json.load(open('$CONFIG_PATH'))['db_storage_dir'])")"
CSV_PATH="$DB_STORAGE_DIR/big_sample.csv"

cd "$HERE"

if [[ -f "$CSV_PATH" ]]; then
    echo "$CSV_PATH already exists, skipping generation (delete it to regenerate)"
else
    echo "generating $N_ROWS rows -> $CSV_PATH ..."
    python3 generate_big_csv.py "$N_ROWS"
fi

echo "loading $CSV_PATH ..."
python3 load_csv.py

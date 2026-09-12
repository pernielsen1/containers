#!/usr/bin/env bash
# Loads a_cust/c_cust/d_cust from <env>/input into the "download"
# database for that environment. prod and test each have their own
# config.json -> own db_storage_dir, so the same "download" db name
# never collides between environments.
# Usage: ./load.sh --env prod|test
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ENV=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --env) ENV="$2"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 1 ;;
    esac
done

if [[ "$ENV" != "prod" && "$ENV" != "test" ]]; then
    echo "usage: load.sh --env prod|test" >&2
    exit 1
fi

INPUT_DIR="$HERE/$ENV/input"

for table in a_cust c_cust d_cust; do
    python3 "$HERE/load_table.py" "$INPUT_DIR/$table.csv" download "$table" --env "$ENV"
done

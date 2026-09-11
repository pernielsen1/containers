#!/usr/bin/env bash
# Builds example.db (via csv_to_sqlite.py) and drops you into its
# interactive client -- `python3 -m sqlite3`, no extra download needed.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_PATH="$HERE/config.json"

DB_STORAGE_DIR="$(python3 -c "import json; print(json.load(open('$CONFIG_PATH'))['db_storage_dir'])")"
DB_PATH="$DB_STORAGE_DIR/example.db"

echo "building $DB_PATH ..."
(cd "$HERE" && python3 csv_to_sqlite.py > /dev/null)

echo "opening client on $DB_PATH -- note: this minimal shell only runs raw SQL + .quit,"
echo "no .tables/.schema (try: SELECT name FROM sqlite_master WHERE type='table';)"
python3 -m sqlite3 "$DB_PATH"

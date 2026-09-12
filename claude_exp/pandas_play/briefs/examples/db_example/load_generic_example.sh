#!/usr/bin/env bash
# Two small CSVs, two tables, one database -- exercises load_csv.py's
# generic path: table_1.a_number -> float, table_2.a_float -> int,
# table_2.a_date -> date (see field_definitions.csv); key/key2/desc
# stay default str.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_PATH="$HERE/config.json"
cd "$HERE"

python3 load_csv.py table_1.csv generic_example table_1
python3 load_csv.py table_2.csv generic_example table_2

DB_STORAGE_DIR="$(python3 -c "import json; print(json.load(open('$CONFIG_PATH'))['db_storage_dir'])")"
DB_PATH="$DB_STORAGE_DIR/generic_example.db"

echo "opening client on $DB_PATH -- note: this minimal shell only runs raw SQL + .quit,"
echo "no .tables/.schema (try: SELECT name FROM sqlite_master WHERE type='table';)"
python3 -m sqlite3 "$DB_PATH"

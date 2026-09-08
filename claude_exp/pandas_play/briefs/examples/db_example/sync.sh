#!/usr/bin/env bash
# Copies the db_example .db files (from db_storage_dir, per config.json)
# into a folder inside OneDrive, as closed at-rest snapshots.
#
# This never runs the other direction: the live/working .db files stay
# in db_storage_dir (local temp, not synced) -- OneDrive only ever gets
# an overwritten "latest" copy, never the live working file.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_PATH="$HERE/config.json"

DB_STORAGE_DIR="$(python3 -c "import json; print(json.load(open('$CONFIG_PATH'))['db_storage_dir'])")"
ONEDRIVE_SYNC_DIR="$(python3 -c "import json; print(json.load(open('$CONFIG_PATH'))['onedrive_sync_dir'])")"

if [[ ! -d "$DB_STORAGE_DIR" ]]; then
    echo "error: db_storage_dir '$DB_STORAGE_DIR' does not exist yet -- run one of the example scripts first." >&2
    exit 1
fi

mkdir -p "$ONEDRIVE_SYNC_DIR"

shopt -s nullglob
db_files=("$DB_STORAGE_DIR"/*.db)
shopt -u nullglob

if [[ ${#db_files[@]} -eq 0 ]]; then
    echo "no .db files found in $DB_STORAGE_DIR -- nothing to sync."
    exit 0
fi

TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
LOG_FILE="$DB_STORAGE_DIR/sync.log"

echo "syncing ${#db_files[@]} database file(s) to $ONEDRIVE_SYNC_DIR"
for f in "${db_files[@]}"; do
    name="$(basename "$f")"
    cp "$f" "$ONEDRIVE_SYNC_DIR/$name"
    size="$(stat -c%s "$f")"
    echo "$TIMESTAMP  $name  ${size} bytes" >> "$LOG_FILE"
    echo "  $name (${size} bytes)"
done

echo "done. log: $LOG_FILE"

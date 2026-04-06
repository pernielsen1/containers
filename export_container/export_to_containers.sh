#!/usr/bin/env bash
# export_to_containers.sh — Copy verified code to ~/containers/AnaCreditExport
#
# Run this after you have tested the container locally and are satisfied.
# The AnaCreditExport directory is the staging area for GitHub sync.
#
# Usage:
#   ./export_to_containers.sh [--dry-run]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$HOME/containers/AnaCreditExport"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

echo "Source : $SCRIPT_DIR"
echo "Target : $TARGET"
[[ "$DRY_RUN" == "true" ]] && echo "[dry-run mode — no files will be written]"
echo ""

rsync_args=(-av --delete \
  --exclude='.git' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='docs/*.pdf' \
  --exclude='docs/*.xlsx' \
  --exclude='.env' \
)

if [[ "$DRY_RUN" == "true" ]]; then
  rsync_args+=(--dry-run)
fi

rsync "${rsync_args[@]}" "$SCRIPT_DIR/" "$TARGET/"

echo ""
if [[ "$DRY_RUN" == "true" ]]; then
  echo "Dry-run complete. Re-run without --dry-run to apply."
else
  echo "Export complete: $TARGET"
  echo "To push to GitHub: cd $TARGET && ./push_container.sh"
fi

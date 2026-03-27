#!/usr/bin/env bash
# deploy.sh — sync clexp/experiments → ../containers/experiments
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/experiments" && pwd)"
DST="$(cd "$(dirname "${BASH_SOURCE[0]}")/../containers/experiments" && pwd)"

echo "Source : $SRC"
echo "Dest   : $DST"
echo ""

rsync -av --delete \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.DS_Store' \
    "$SRC/" "$DST/"

echo ""
echo "Done."

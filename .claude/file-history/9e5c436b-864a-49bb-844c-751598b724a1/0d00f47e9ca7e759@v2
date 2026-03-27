#!/usr/bin/env bash
# deploy.sh — sync clexp/AnaCredit → ../containers/AnaCredit
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DST="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../containers/AnaCredit" 2>/dev/null || { mkdir -p "$(dirname "${BASH_SOURCE[0]}")/../../containers/AnaCredit" && cd "$(dirname "${BASH_SOURCE[0]}")/../../containers/AnaCredit" && pwd; })"

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

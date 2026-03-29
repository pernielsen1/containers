#!/bin/bash
# Run before leaving a laptop to sync Claude memory/settings and push everything.
# On the other laptop: git pull to resume with full context.
# Calls clexp deploy scripts to pull in latest experiments and AnaCredit changes.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLEXP_DIR="$HOME/clexp"

# --- sync clexp content into containers ---
# echo "==> Syncing experiments..."
# bash "$CLEXP_DIR/deploy.sh"

# echo "==> Syncing AnaCredit..."
# bash "$CLEXP_DIR/AnaCredit/deploy.sh"


# --- commit and push ---
cd "$SCRIPT_DIR"
git add .
git commit
REMOTE_URL="github.com/$GIT_USER/containers.git"
git push -u https://$GIT_USER:$GIT_ACCESS_TOKEN@$REMOTE_URL main

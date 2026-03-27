#!/bin/bash
# Run before leaving a laptop to sync Claude memory/settings and push everything.
# On the other laptop: git pull to resume with full context.
# Note: experiments and AnaCredit are synced via their own deploy.sh scripts.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- sync Claude memory + settings ---
rsync -a --delete \
    --exclude 'todos/' \
    --exclude 'ide/' \
    --exclude '*.log' \
    --exclude 'statsig/' \
    --exclude 'cache/' \
    "$HOME/.claude/" "$SCRIPT_DIR/.claude/"

# --- commit and push ---
cd "$SCRIPT_DIR"
git add .
git commit
REMOTE_URL="github.com/$GIT_USER/containers.git"
git push -u https://$GIT_USER:$GIT_ACCESS_TOKEN@$REMOTE_URL main

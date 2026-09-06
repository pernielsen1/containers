#!/usr/bin/env bash
# Fixes a bug in 03_push_and_swap.sh: `git rm -r claude_exp/routers` only removes files git was
# tracking - it leaves untracked files/directories in place (build artifacts, certs, local
# settings, etc.). Since claude_exp/routers therefore still existed as a non-empty directory, the
# script's `mv ~/routers-extracted claude_exp/routers` nested the new repo one level too deep, at
# claude_exp/routers/routers-extracted/, instead of replacing claude_exp/routers itself.
#
# This script has already been verified (by Claude, this session) to be safe to run: every
# top-level entry left behind at claude_exp/routers (crypto_host, router_cpp, router_java,
# router_py, upstream_host, .claude, .github, done) was inventoried and confirmed to be disposable
# - router_cpp/router_java build output (~1.3GB combined), regeneratable TLS certs, local Claude
# Code settings, an old unrelated tooling-artifact .github folder (not CI config, and not present
# in the correctly-extracted copy at all). None of it is git-tracked content; none of it exists in
# routers-extracted's history.
#
# What this does:
#   1. Deletes every top-level entry under claude_exp/routers EXCEPT routers-extracted/.
#   2. Moves routers-extracted's contents (including .git, .gitignore) up one level.
#   3. Removes the now-empty routers-extracted directory.
set -euo pipefail

ROUTERS_DIR="$HOME/containers/claude_exp/routers"
NESTED="$ROUTERS_DIR/routers-extracted"

if [ ! -d "$NESTED/.git" ]; then
  echo "ERROR: $NESTED isn't a git repo - nothing to fix, or this was already fixed." >&2
  exit 1
fi

echo "[1/3] Removing leftover untracked junk in $ROUTERS_DIR (everything except routers-extracted)..."
find "$ROUTERS_DIR" -maxdepth 1 -mindepth 1 ! -name routers-extracted -print -exec rm -rf {} +

echo "[2/3] Moving routers-extracted's contents up one level (including dotfiles)..."
shopt -s dotglob
mv "$NESTED"/* "$ROUTERS_DIR"/
rmdir "$NESTED"

echo "[3/3] Verifying..."
cd "$ROUTERS_DIR"
echo "  top-level repo root is now:"
git rev-parse --show-toplevel
echo "  remote:"
git remote -v
echo "  commit count:"
git log --oneline | wc -l
echo "  status (blank = clean):"
git status --short

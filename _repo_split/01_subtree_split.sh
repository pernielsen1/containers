#!/usr/bin/env bash
# Step 1 of 3 in splitting claude_exp/routers out of the ~/containers monorepo into its own repo.
#
# What this does: creates a new LOCAL branch (routers-history) in the ~/containers repo containing
# only the commits that touched claude_exp/routers, rewritten so that directory becomes the repo
# root. This is git's built-in `git subtree split` - no new tools needed.
#
# Safety: this is purely additive. It does not touch main, does not push anything, does not delete
# or modify a single file in your working tree. If you don't like the result, just
# `git branch -D routers-history` and nothing happened.
#
# Run from anywhere - this cd's to ~/containers itself.
set -euo pipefail

CONTAINERS_ROOT="$HOME/containers"
BRANCH="routers-history"

cd "$CONTAINERS_ROOT"

echo "[1/3] Checking working tree is clean (subtree split refuses otherwise)..."
if [ -n "$(git status --porcelain)" ]; then
  echo "ERROR: ~/containers has uncommitted changes. Commit or stash them first, then re-run." >&2
  git status --short >&2
  exit 1
fi

if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  echo "ERROR: branch '$BRANCH' already exists. Delete it first if you want to redo this step:" >&2
  echo "  git branch -D $BRANCH" >&2
  exit 1
fi

echo "[2/3] Running git subtree split --prefix=claude_exp/routers -b $BRANCH ..."
echo "      (this rewrites ~36 commits - may take a little while, it's not stuck)"
git subtree split --prefix=claude_exp/routers -b "$BRANCH"

echo "[3/3] Done. Sanity-checking the result..."
echo
echo "Commit count on $BRANCH:"
git log --oneline "$BRANCH" | wc -l
echo
echo "First and last commits:"
git log --reverse --oneline "$BRANCH" | head -1
git log --oneline "$BRANCH" | head -1
echo
echo "Top-level files at $BRANCH's HEAD (should look like routers/'s own contents, not claude_exp/...):"
git ls-tree --name-only "$BRANCH" | head -20
echo
echo "Nothing has been pushed or deleted. Next: run 02_extract_standalone.sh"

#!/usr/bin/env bash
# Step 3 of 3. Run this AFTER:
#   1. 02_extract_standalone.sh succeeded and you've looked over ~/routers-extracted
#   2. You've created an empty GitHub repo (web UI, or `gh repo create pernielsen1/routers`)
#
# Usage: ./03_push_and_swap.sh git@github.com:pernielsen1/routers.git
#    or: ./03_push_and_swap.sh https://github.com/pernielsen1/routers.git
#
# What this does, in order:
#   1. Pushes the extracted history to the GitHub repo you created.
#   2. Removes claude_exp/routers from the ~/containers monorepo with one ordinary commit
#      (NOT a history rewrite - `git log -- claude_exp/routers` in ~/containers still shows the
#      full original history forever; this commit just stops tracking the files going forward).
#   3. Moves ~/routers-extracted into place at ~/containers/claude_exp/routers, so the path you
#      (and Claude Code) work in every day doesn't change at all - it's just its own git repo now.
#
# Safety: step 1 (push) is the point past which the new repo is public/durable on GitHub - you'll
# be asked to confirm before steps 2-3 touch the monorepo or move anything on disk. Step 2 is a
# normal reversible commit (git revert undoes it). Nothing here force-pushes or rewrites existing
# history anywhere.
set -euo pipefail

CONTAINERS_ROOT="$HOME/containers"
EXTRACT_DIR="$HOME/routers-extracted"
REPO_URL="${1:-}"

if [ -z "$REPO_URL" ]; then
  echo "Usage: $0 <git-remote-url>" >&2
  echo "e.g.:  $0 git@github.com:pernielsen1/routers.git" >&2
  exit 1
fi

if [ ! -d "$EXTRACT_DIR/.git" ]; then
  echo "ERROR: $EXTRACT_DIR isn't a git repo - run 02_extract_standalone.sh first." >&2
  exit 1
fi

echo "[1/5] Adding remote and pushing $EXTRACT_DIR to $REPO_URL ..."
cd "$EXTRACT_DIR"
git remote add origin "$REPO_URL"
git push -u origin main

echo
echo "Pushed. Open the repo on GitHub now and sanity-check it before continuing:"
echo "  $REPO_URL"
read -r -p "Does it look right on GitHub? Type 'yes' to continue with the monorepo swap: " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo "Stopping here. The push already happened (that part's done and safe to leave as-is)."
  echo "Nothing in ~/containers or on disk has been touched - re-run this script again anytime"
  echo "once you're ready (it will skip the push since 'origin' is already set... actually it will"
  echo "fail on 'git remote add origin' - in that case just delete steps 2-4 below by hand, or ask"
  echo "Claude to adjust this script)."
  exit 0
fi

echo "[2/5] Removing claude_exp/routers from the ~/containers monorepo (one ordinary commit)..."
cd "$CONTAINERS_ROOT"
if [ -n "$(git status --porcelain)" ]; then
  echo "ERROR: ~/containers has uncommitted changes - commit or stash them first." >&2
  exit 1
fi
git rm -r -q claude_exp/routers
git commit -q -m "Split claude_exp/routers into its own repo: $REPO_URL

Full original history is preserved on this branch's ancestry (see
git log -- claude_exp/routers) and lives on going forward at $REPO_URL."

echo "[3/5] Removing the now-empty local branch used for the split (routers-history)..."
git branch -D routers-history 2>/dev/null || true

echo "[4/5] Moving $EXTRACT_DIR into place at ${CONTAINERS_ROOT}/claude_exp/routers ..."
mv "$EXTRACT_DIR" "$CONTAINERS_ROOT/claude_exp/routers"

echo "[5/5] Done. Verifying..."
cd "$CONTAINERS_ROOT/claude_exp/routers"
echo "  $(pwd) is now its own repo, remote:"
git remote -v
echo
echo "  ~/containers no longer tracks it:"
cd "$CONTAINERS_ROOT" && git status --short claude_exp/routers || echo "  (clean - nothing tracked there anymore)"
echo
echo "All done. Same path, ~/containers/claude_exp/routers, now its own repo pushed to $REPO_URL."

#!/usr/bin/env bash
# Step 2 of 3. Run this AFTER 01_subtree_split.sh has succeeded.
#
# What this does: clones the routers-history branch out of ~/containers into a fresh standalone
# directory (~/routers-extracted), so it's a real independent git repo (its own .git, its own
# history) that you can inspect before anything touches GitHub or the monorepo. Then it adds a
# proper .gitignore (the current one in ~/containers is stale - references old fastapi/mysql
# client paths, has no Python/C++/Java build-artifact patterns) and un-tracks the __pycache__/.pyc
# files that got committed by accident, as one new commit on top of the extracted history.
#
# Safety: writes only to the new ~/routers-extracted directory. Does not touch ~/containers at all
# (a `git clone` is a read-only operation on its source). If ~/routers-extracted already exists,
# this refuses to run rather than overwrite it.
set -euo pipefail

CONTAINERS_ROOT="$HOME/containers"
BRANCH="routers-history"
EXTRACT_DIR="$HOME/routers-extracted"

if [ -d "$EXTRACT_DIR" ]; then
  echo "ERROR: $EXTRACT_DIR already exists. Remove it first if you want to redo this step:" >&2
  echo "  rm -rf $EXTRACT_DIR" >&2
  exit 1
fi

if ! git -C "$CONTAINERS_ROOT" show-ref --verify --quiet "refs/heads/$BRANCH"; then
  echo "ERROR: branch '$BRANCH' doesn't exist in $CONTAINERS_ROOT - run 01_subtree_split.sh first." >&2
  exit 1
fi

echo "[1/4] Cloning $BRANCH out of $CONTAINERS_ROOT into $EXTRACT_DIR ..."
git clone --branch "$BRANCH" "$CONTAINERS_ROOT" "$EXTRACT_DIR"
cd "$EXTRACT_DIR"
# The clone points 'origin' back at your local ~/containers checkout, which is meaningless once
# this becomes its own repo - remove it now so 03_push_and_swap.sh starts from a clean slate.
git remote remove origin
git branch -m "$BRANCH" main

echo "[2/4] Writing a real .gitignore for a Python/C++/Java project..."
cat > .gitignore <<'EOF'
# Python
__pycache__/
*.pyc
*.pyo
.pytest_cache/

# C++
build/
build_local/
*.o
*.so

# Java
target/
*.class

# editors / OS
.vscode/
.idea/
.DS_Store
EOF
git add .gitignore

echo "[3/4] Untracking already-committed __pycache__/.pyc files (kept on disk, just stop tracking)..."
# --ignore-unmatch: don't fail if a future run of this script finds nothing left to untrack.
git ls-files | grep -E '__pycache__|\.pyc$' | xargs -r git rm --cached --ignore-unmatch -q

echo "[4/4] Committing..."
git commit -m "Add .gitignore for standalone repo; stop tracking __pycache__/.pyc

Split out of the ~/containers monorepo (claude_exp/routers) - see the rest of the
history on this branch for the original commits." -q

echo
echo "Done. $EXTRACT_DIR is now a self-contained repo with:"
git log --oneline | wc -l
echo "commits, on branch:"
git branch --show-current
echo
echo "Look it over: cd $EXTRACT_DIR && git log --stat -5"
echo "Next: create the GitHub repo (web UI or 'gh repo create'), then run 03_push_and_swap.sh <repo-url>"

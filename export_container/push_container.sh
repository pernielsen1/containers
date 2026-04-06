#!/usr/bin/env bash
# push_container.sh — Commit and push the AnaCredit container to GitHub.
#
# Requires:
#   GIT_USER_NAME    GitHub username
#   GIT_ACCESS_TOKEN GitHub personal access token (repo scope)
#
# Usage:
#   ./push_container.sh [--message "commit message"] [--repo anacredit-container]

set -euo pipefail

REPO_NAME="${REPO_NAME:-anacredit-container}"
COMMIT_MSG="sync"
BRANCH="main"

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --message|-m) COMMIT_MSG="$2"; shift 2 ;;
    --repo|-r)    REPO_NAME="$2";  shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

# Validate env vars
if [[ -z "${GIT_USER_NAME:-}" ]]; then
  echo "ERROR: GIT_USER_NAME is not set."
  exit 1
fi
if [[ -z "${GIT_ACCESS_TOKEN:-}" ]]; then
  echo "ERROR: GIT_ACCESS_TOKEN is not set."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Build authenticated remote URL (token never stored in config)
REMOTE_URL="https://${GIT_USER_NAME}:${GIT_ACCESS_TOKEN}@github.com/${GIT_USER_NAME}/${REPO_NAME}.git"

# Initialize git if needed
if [[ ! -d .git ]]; then
  echo "Initializing git repository..."
  git init
  git checkout -b "$BRANCH"
fi

# Configure identity if not already set
git config user.email "${GIT_USER_NAME}@users.noreply.github.com" 2>/dev/null || true
git config user.name  "${GIT_USER_NAME}" 2>/dev/null || true

# Create/update remote (use transient URL, not stored)
git remote remove origin 2>/dev/null || true
git remote add origin "$REMOTE_URL"

# Stage all tracked + new files (exclude .gitignore'd files)
git add -A

# Check if there is anything to commit
if git diff --cached --quiet; then
  echo "Nothing to commit — already up to date."
else
  git commit -m "$COMMIT_MSG"
  echo "Committed: $COMMIT_MSG"
fi

echo "Pushing to github.com/${GIT_USER_NAME}/${REPO_NAME} ..."
git push -u origin "$BRANCH"
echo "Done."

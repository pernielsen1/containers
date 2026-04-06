#!/usr/bin/env bash
# pull_container.sh — Clone or pull the AnaCredit container from GitHub.
#
# Run this on a new machine to get the latest container code.
#
# Requires:
#   GIT_USER_NAME    GitHub username
#   GIT_ACCESS_TOKEN GitHub personal access token (repo scope)
#
# Usage:
#   ./pull_container.sh [--repo anacredit-container] [--dir ~/myproject]

set -euo pipefail

REPO_NAME="${REPO_NAME:-anacredit-container}"
TARGET_DIR=""
BRANCH="main"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo|-r) REPO_NAME="$2"; shift 2 ;;
    --dir|-d)  TARGET_DIR="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

if [[ -z "${GIT_USER_NAME:-}" ]]; then
  echo "ERROR: GIT_USER_NAME is not set."
  exit 1
fi
if [[ -z "${GIT_ACCESS_TOKEN:-}" ]]; then
  echo "ERROR: GIT_ACCESS_TOKEN is not set."
  exit 1
fi

REMOTE_URL="https://${GIT_USER_NAME}:${GIT_ACCESS_TOKEN}@github.com/${GIT_USER_NAME}/${REPO_NAME}.git"

if [[ -z "$TARGET_DIR" ]]; then
  TARGET_DIR="$HOME/containers/AnaCreditExport"
fi

if [[ -d "${TARGET_DIR}/.git" ]]; then
  echo "Repository exists at ${TARGET_DIR} — pulling latest..."
  cd "$TARGET_DIR"
  # Update remote URL with fresh token
  git remote set-url origin "$REMOTE_URL"
  git pull origin "$BRANCH"
else
  echo "Cloning ${REPO_NAME} into ${TARGET_DIR} ..."
  mkdir -p "$(dirname "$TARGET_DIR")"
  git clone "$REMOTE_URL" "$TARGET_DIR"
  echo "Done. Container is at: ${TARGET_DIR}"
  echo ""
  echo "Next steps:"
  echo "  cd ${TARGET_DIR}"
  echo "  Copy your docs (PDFs, Excel) into docs/"
  echo "  Set ANTHROPIC_API_KEY in your environment"
  echo "  Open in VS Code and choose 'Reopen in Container'"
fi

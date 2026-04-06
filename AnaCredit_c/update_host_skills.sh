#!/usr/bin/env bash
# update_host_skills — copy skills from container workspace to host .claude/commands
#
# Usage: ./update_host_skills.sh [--dry-run]
#
# The host .claude/commands directory is mounted at /host_commands.
# Skills developed in /workspaces/AnaCredit_c/skills/ are deployed there.

set -euo pipefail

SKILLS_SRC="/workspaces/AnaCredit_c/skills"
HOST_COMMANDS="/host_commands"
DRY_RUN=false

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
  echo "[dry-run] No files will be written."
fi

if [[ ! -d "$HOST_COMMANDS" ]]; then
  echo "ERROR: Host commands directory not mounted at $HOST_COMMANDS"
  echo "  Make sure the container is started with the /host_commands bind mount."
  exit 1
fi

if [[ ! -d "$SKILLS_SRC" ]]; then
  echo "ERROR: Skills source directory not found: $SKILLS_SRC"
  exit 1
fi

shopt -s nullglob
files=("$SKILLS_SRC"/*.md)
if [[ ${#files[@]} -eq 0 ]]; then
  echo "No .md skill files found in $SKILLS_SRC — nothing to deploy."
  exit 0
fi

echo "Deploying skills from $SKILLS_SRC → $HOST_COMMANDS"
echo ""

for file in "${files[@]}"; do
  name=$(basename "$file")
  dest="$HOST_COMMANDS/$name"
  if [[ -f "$dest" ]]; then
    if diff -q "$file" "$dest" > /dev/null 2>&1; then
      echo "  [unchanged] $name"
      continue
    fi
    echo "  [update]    $name"
  else
    echo "  [new]       $name"
  fi
  if [[ "$DRY_RUN" == false ]]; then
    cp "$file" "$dest"
  fi
done

echo ""
if [[ "$DRY_RUN" == true ]]; then
  echo "Dry run complete. Re-run without --dry-run to apply."
else
  echo "Done. Skills deployed to host .claude/commands."
fi

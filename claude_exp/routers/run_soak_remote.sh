#!/usr/bin/env bash
# Thin wrapper around run_soak.sh for testing against serverhp.home instead of this host - same
# three phases, same CSV outputs, same server_start.sh/wait_for_stats machinery already wired into
# each stress_run.sh's remote branch (see server_start.sh). This script does NOT duplicate any of
# that phase logic - it only sets the remote-run env vars run_soak.sh already knows how to use
# (ROUTER_HOST, ENV_NAME) and fails fast if the server itself isn't reachable, since run_soak.sh's
# own `set -uo pipefail` (no -e) would otherwise let an unreachable server slip past its own
# "ensure crypto_host is up" step and only surface as a confusing wait_for_stats timeout deep into
# phase 1.
#
# Usage: SERVER_USER=<user> ./run_soak_remote.sh [number_of_minutes]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

SERVER_USER="${SERVER_USER:?SERVER_USER env var must be set}"

echo "Checking serverhp.home is reachable..." >&2
if ! ssh -o ConnectTimeout=5 "${SERVER_USER}@serverhp.home" true 2>/dev/null; then
  echo "ERROR: cannot SSH to serverhp.home - is it powered on/reachable?" >&2
  exit 1
fi

# Ensures crypto_host (the one piece not re-started per phase by stress_run.sh's remote branch -
# see server_start.sh) is actually up and responding before the soak starts, rather than relying
# on run_soak.sh's own equivalent call further down, which can't abort the run if it fails (its
# `set -uo pipefail` has no -e - see this script's header comment).
echo "Ensuring crypto_host is up on serverhp.home..." >&2
SERVER_USER="$SERVER_USER" ./server_start.sh crypto >&2

export SERVER_USER
export ROUTER_HOST="serverhp.home"
# Tags every csv_results/*.csv row from this run as serverhp.home rather than this host's own
# hostname - see run_soak.sh's ENV_NAME comment and today's "env column" addition to the CSVs.
export ENV_NAME="serverhp.home"
exec ./run_soak.sh "$@"

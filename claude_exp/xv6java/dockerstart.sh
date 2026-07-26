#!/bin/bash
# Ensures the Docker daemon is running. Separate from start.sh so it can be re-run on its own
# (e.g. after this container/VM was reclaimed and restarted) without triggering a rebuild.
#
# `service docker start` fails in some restricted-capability sandboxes (ulimit errors inside
# /etc/init.d/docker) even though the daemon itself starts fine when launched directly - so this
# tries the normal path first and falls back to a direct `dockerd` if that doesn't work.
set -euo pipefail

if docker info >/dev/null 2>&1; then
  echo "Docker daemon already running."
  exit 0
fi

echo "Docker daemon not running; trying 'service docker start'..."
# dockerd manages network namespaces/cgroups/iptables, which requires root - being in the
# `docker` group only lets the *client* talk to an already-running daemon without sudo. `sudo`
# here will prompt for a password when this script is run interactively; if there's no
# password prompt available (e.g. a non-interactive session), it fails fast rather than hanging.
sudo service docker start >/dev/null 2>&1 || true

for _ in $(seq 1 10); do
  docker info >/dev/null 2>&1 && { echo "Docker daemon is up."; exit 0; }
  sleep 1
done

echo "'service docker start' didn't bring it up; starting dockerd directly..."
sudo nohup dockerd >/tmp/dockerd.log 2>&1 &
disown

for _ in $(seq 1 30); do
  docker info >/dev/null 2>&1 && { echo "Docker daemon is up (direct dockerd)."; exit 0; }
  sleep 1
done

echo "Docker daemon did not come up. See /tmp/dockerd.log for details." >&2
exit 1

#!/bin/bash
# POST /stop to the monitor, poll its PID (from run/.monitor.pid, written by run/monitor.sh)
# for up to 30s, then SIGKILL if it hasn't exited — covers a monitor that's wedged or has
# a stuck subprocess.
cd "$(dirname "$0")/.."
PORT="${1:-8090}"
PIDFILE="run/.monitor.pid"

curl -s -X POST "http://127.0.0.1:${PORT}/stop" >/dev/null || true

if [ ! -f "$PIDFILE" ]; then
  echo "no pidfile at $PIDFILE — monitor wasn't started via run/monitor.sh, or already stopped"
  exit 0
fi
PID=$(cat "$PIDFILE")

for _ in $(seq 1 30); do
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "monitor stopped"
    rm -f "$PIDFILE"
    exit 0
  fi
  sleep 1
done

echo "monitor did not stop within 30s, sending SIGKILL"
kill -9 "$PID" 2>/dev/null || true
rm -f "$PIDFILE"

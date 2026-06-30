#!/bin/bash
set -e
cd "$(dirname "$0")/.."
PIDFILE="run/.monitor.pid"

if [ ! -f "$PIDFILE" ]; then
  echo "no pidfile at $PIDFILE"
  exit 1
fi

PID=$(cat "$PIDFILE")

# Try graceful stop first
curl -s -X POST "http://127.0.0.1:8090/stop" || true

# Poll for exit
for i in $(seq 1 30); do
  if ! kill -0 "$PID" 2>/dev/null; then
    rm -f "$PIDFILE"
    echo "monitor stopped"
    exit 0
  fi
  sleep 1
done

# SIGKILL fallback
echo "monitor did not stop — sending SIGKILL"
kill -9 "$PID" || true
rm -f "$PIDFILE"

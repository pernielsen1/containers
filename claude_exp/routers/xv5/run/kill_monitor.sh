#!/bin/bash
cd "$(dirname "$0")/.."
PIDFILE="run/.monitor.pid"

curl -s -X POST http://127.0.0.1:8090/stop > /dev/null 2>&1 || true

if [ -f "$PIDFILE" ]; then
  PID=$(cat "$PIDFILE")
  for _ in $(seq 1 30); do
    if ! kill -0 "$PID" 2>/dev/null; then
      break
    fi
    sleep 1
  done
  if kill -0 "$PID" 2>/dev/null; then
    kill -9 "$PID" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
fi

echo "monitor stopped"

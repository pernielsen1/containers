#!/bin/bash
# POST /stop, then poll the PID from monitor_start.sh's pidfile for up to 30s, SIGKILL if still
# alive, then remove the pidfile. Deliberately not `pgrep -f "monitor/main.py"` - that pattern
# has already bitten this project family once (matched an unrelated process by command-line
# substring and left a zombie monitor alive on this exact port for hours).
cd "$(dirname "$0")"
PIDFILE=".monitor.pid"

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

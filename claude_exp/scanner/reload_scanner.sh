#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/scanner.pid"

if [[ ! -f "$PID_FILE" ]]; then
    echo "No PID file found — scanner may not be running."
    exit 1
fi

PID=$(cat "$PID_FILE")
if kill -0 "$PID" 2>/dev/null; then
    kill -HUP "$PID"
    echo "Reload signal sent to scanner (pid $PID)."
else
    echo "Process $PID not found — scanner is not running."
    exit 1
fi

#!/usr/bin/env bash
# Stop the scanner daemon.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/scanner.pid"

# Try systemd first
if command -v systemctl &>/dev/null && systemctl --user is-active --quiet scanner.service 2>/dev/null; then
    systemctl --user stop scanner.service
    echo "Scanner stopped (systemd)."
    exit 0
fi

# Fall back to PID file
if [[ ! -f "$PID_FILE" ]]; then
    echo "No PID file found at $PID_FILE — scanner may not be running."
    exit 1
fi

PID=$(cat "$PID_FILE")
if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    rm "$PID_FILE"
    echo "Scanner stopped (pid $PID)."
else
    echo "Process $PID not found — cleaning up PID file."
    rm "$PID_FILE"
fi

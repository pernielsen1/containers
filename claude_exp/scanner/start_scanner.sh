#!/usr/bin/env bash
# Start scanner as a background daemon without installing.
# Process will appear as "pn_scanner" in ps.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCANNER="$SCRIPT_DIR/scanner.py"
PID_FILE="$SCRIPT_DIR/scanner.pid"
LOG_FILE="$SCRIPT_DIR/scanner.log"

if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Scanner already running (pid $PID)."
        exit 0
    fi
    rm "$PID_FILE"
fi

nohup bash -c "exec -a pn_scanner python3 \"$SCANNER\"" >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
echo "Scanner started (pid $(cat "$PID_FILE"))."

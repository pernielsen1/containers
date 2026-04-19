#!/usr/bin/env bash
# Install scanner as a background service.
# Works on Linux/WSL (systemd or nohup fallback) and detects Windows via COMSPEC.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCANNER="$SCRIPT_DIR/scanner.py"
PID_FILE="$SCRIPT_DIR/scanner.pid"

# Windows via Git Bash / COMSPEC
if [[ -n "$COMSPEC" ]]; then
    echo "Windows detected — launching via pythonw"
    pythonw "$SCANNER" &
    echo $! > "$PID_FILE"
    echo "Scanner started (pid $(cat "$PID_FILE"))"
    exit 0
fi

# Linux / WSL — prefer systemd, fall back to nohup
if command -v systemctl &>/dev/null && systemctl --user status &>/dev/null 2>&1; then
    SERVICE_FILE="$HOME/.config/systemd/user/scanner.service"
    mkdir -p "$(dirname "$SERVICE_FILE")"
    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=File Scanner Daemon

[Service]
ExecStart=/bin/bash -c "exec -a pn_scanner python3 $SCANNER"
Restart=on-failure

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now scanner.service
    echo "Scanner installed and started via systemd (user service)."
else
    echo "Starting scanner with nohup..."
    nohup bash -c "exec -a pn_scanner python3 \"$SCANNER\"" >> "$SCRIPT_DIR/scanner.log" 2>&1 &
    echo $! > "$PID_FILE"
    echo "Scanner started (pid $(cat "$PID_FILE"))"
fi

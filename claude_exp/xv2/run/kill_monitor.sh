#!/usr/bin/env bash
set -uo pipefail

MONITOR_PORT=${MONITOR_PORT:-8090}

# Capture PID before sending stop so we can track it
MONITOR_PID=$(pgrep -f "monitor/main.py" 2>/dev/null || true)

echo "Sending stop to monitor on port ${MONITOR_PORT}..."
curl -s -X POST "http://localhost:${MONITOR_PORT}/stop" > /dev/null 2>&1 || true

if [ -z "${MONITOR_PID}" ]; then
    echo "No monitor process found."
    exit 0
fi

echo "Waiting for PID ${MONITOR_PID} to exit..."
for i in $(seq 1 30); do
    if ! kill -0 "${MONITOR_PID}" 2>/dev/null; then
        echo "Monitor stopped."
        exit 0
    fi
    sleep 1
done

echo "Monitor did not stop after 30s — sending SIGKILL to PID ${MONITOR_PID}."
kill -9 "${MONITOR_PID}" 2>/dev/null || true

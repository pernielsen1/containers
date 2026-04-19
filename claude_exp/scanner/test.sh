#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$SCRIPT_DIR/to_upper/hello.txt"

if [[ -f "$TARGET" ]]; then
    echo "Error: $TARGET already exists."
    exit 1
fi

echo "Hello Claude" > "$TARGET"
echo "Created: $TARGET"

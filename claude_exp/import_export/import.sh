#!/usr/bin/env bash
# Import pandas and pyiso8583 from the exported tar file.
set -euo pipefail

SCRIPT_DIR="$(dirname "$(realpath "$0")")"
TARFILE="${1:-$SCRIPT_DIR/iso8583_packages.tar.gz}"

if [[ ! -f "$TARFILE" ]]; then
    echo "ERROR: tar file not found: $TARFILE"
    echo "Usage: $0 [path/to/iso8583_packages.tar.gz]"
    exit 1
fi

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

tar -xzf "$TARFILE" -C "$TMPDIR"

pip install \
    --no-index \
    --find-links "$TMPDIR/pkg_export" \
    pandas \
    pyiso8583

echo "Done — pandas and pyiso8583 installed from $TARFILE"

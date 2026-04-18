#!/usr/bin/env bash
# Export pandas, pyiso8583 and their dependencies as a tar of wheel files.
set -euo pipefail

OUTDIR="$(dirname "$(realpath "$0")")/pkg_export"
TARFILE="$(dirname "$(realpath "$0")")/iso8583_packages.tar.gz"

rm -rf "$OUTDIR"
mkdir -p "$OUTDIR"

pip download \
    pandas \
    pyiso8583 \
    --dest "$OUTDIR" \
    --no-cache-dir

tar -czf "$TARFILE" -C "$(dirname "$OUTDIR")" pkg_export

echo "Created: $TARFILE"
echo "Copy this file to the target machine and run import.sh"

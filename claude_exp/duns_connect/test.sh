#!/bin/bash
set -e

echo "Cleaning output directory..."
rm -f output/*

echo "Running fetch_duns_info.py..."
python3 src/fetch_duns_info.py "$@"

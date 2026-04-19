#!/usr/bin/env python3
"""Action: convert file content to uppercase in-place."""
import sys

if len(sys.argv) < 2:
    print("Usage: upper.py <filepath>", file=sys.stderr)
    sys.exit(1)

filepath = sys.argv[1]
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content.upper())

print(f"Uppercased: {filepath}")
sys.exit(0)

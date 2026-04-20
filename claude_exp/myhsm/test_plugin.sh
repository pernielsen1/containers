#!/usr/bin/env bash
set -e

BASE_URL="${1:-http://localhost:5000}"
USERNAME="admin"
PASSWORD="admin123"
INPUT="${2:-hello world}"

echo "--- Login ---"
TOKEN=$(curl -s -X POST "$BASE_URL/sys/v1/session/auth" \
  -u "$USERNAME:$PASSWORD" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "Token: $TOKEN"

echo ""
echo "--- Invoke upper_case plugin ---"
curl -s -X POST "$BASE_URL/crypto/v1/plugins/upper_case" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"input\": \"$INPUT\"}" | python3 -m json.tool

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

echo ""
echo "--- Invoke arqc plugin (PAN=555551234567890, PSN=01, amount=1234, currency=978) ---"
ARQC_RESP=$(curl -s -X POST "$BASE_URL/crypto/v1/plugins/arqc" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "imk_token": "des_key",
    "pan": "555551234567890",
    "psn": "01",
    "amount": 1234,
    "currency": 978,
    "terminal_country": "0978",
    "atc": "0001"
  }')
echo "$ARQC_RESP" | python3 -m json.tool
ARQC=$(echo "$ARQC_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['arqc'])")

echo ""
echo "--- Invoke arpc plugin method 1 (ARC=0000 approved) ---"
curl -s -X POST "$BASE_URL/crypto/v1/plugins/arpc" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"imk_token\": \"des_key\",
    \"pan\": \"555551234567890\",
    \"psn\": \"01\",
    \"atc\": \"0001\",
    \"arqc\": \"$ARQC\",
    \"arc\": \"0000\",
    \"arpc_method\": \"1\"
  }" | python3 -m json.tool

echo ""
echo "--- Invoke arpc plugin method 2 (ARC=0000, CSU=00000000) ---"
curl -s -X POST "$BASE_URL/crypto/v1/plugins/arpc" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"imk_token\": \"des_key\",
    \"pan\": \"555551234567890\",
    \"psn\": \"01\",
    \"atc\": \"0001\",
    \"arqc\": \"$ARQC\",
    \"arc\": \"0000\",
    \"arpc_method\": \"2\"
  }" | python3 -m json.tool

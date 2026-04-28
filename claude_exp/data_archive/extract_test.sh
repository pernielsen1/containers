#!/usr/bin/env bash
# Test: run this script, then inspect extract/account_deposit.json
# Expected: file exists and contains valid JSON with holder, balance, currency fields
# Quick check: bash extract_test.sh && cat extract/account_deposit.json

python3 extract.py account deposit

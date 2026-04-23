#!/usr/bin/env bash
# Regression tests for duplicate_v2.
#
# Run from the duplicate_v2 directory:
#   bash regression/test.sh
#
# Exit code: 0 = all passed, 1 = one or more failed.

set -uo pipefail

# ── Setup ─────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$(dirname "$SCRIPT_DIR")"   # move to duplicate_v2/

PASS=0; FAIL=0
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

SOURCE_CSV="../find_duplicates/test_counterparties.csv"
NEW_CSV="new_counterparties.csv"

# ── Helpers ───────────────────────────────────────────────────────────────────

pass() { printf "  PASS  %s\n" "$1"; PASS=$((PASS + 1)); }
fail() { printf "  FAIL  %s\n" "$1"; FAIL=$((FAIL + 1)); }

# Count data rows (excluding header) in a semicolon-delimited CSV
rows() {
    python3 - "$1" << 'PY'
import csv, sys
with open(sys.argv[1], encoding="utf-8-sig") as f:
    print(sum(1 for _ in csv.DictReader(f, delimiter=";")))
PY
}

check_rows() {
    local label="$1" file="$2" expected="$3"
    local actual
    actual=$(rows "$file")
    if [ "$actual" -eq "$expected" ]; then
        pass "$label (${actual} rows)"
    else
        fail "$label — expected ${expected} rows, got ${actual}"
    fi
}

has() {
    local label="$1" file="$2" pattern="$3"
    if grep -q "$pattern" "$file" 2>/dev/null; then
        pass "$label"
    else
        fail "$label — '$pattern' not found in $(basename "$file")"
    fi
}

not_has() {
    local label="$1" file="$2" pattern="$3"
    if grep -q "$pattern" "$file" 2>/dev/null; then
        fail "$label — '$pattern' should not be in $(basename "$file")"
    else
        pass "$label"
    fi
}

runs_ok() {
    local label="$1"; shift
    if python3 "$@" > /dev/null 2>&1; then
        pass "$label"
    else
        fail "$label — script exited with error"
    fi
}

# ── Group 1: init_counterparties.py — trigram (default) ──────────────────────

echo ""
echo "── init_counterparties.py  method=trigram (default) ──"

OUT="$TMP/cp_tri.csv"
runs_ok  "T01 runs without error" \
    init_counterparties.py "$SOURCE_CSV" --output "$OUT"

check_rows "T02 7 unique records kept"                "$OUT" 7
has        "T03 CP-001 kept (first Deutsche Bank)"    "$OUT" "CP-001"
not_has    "T04 CP-002 dropped (exact dup)"           "$OUT" "CP-002"
not_has    "T05 CP-004 dropped (Mueller variant)"     "$OUT" "CP-004"
not_has    "T06 CP-006 dropped (Commerz Bank)"        "$OUT" "CP-006"
not_has    "T07 CP-008 dropped (Siemens alt address)" "$OUT" "CP-008"
not_has    "T08 CP-013 dropped (Deutsche Bankhaus)"   "$OUT" "CP-013"
not_has    "T09 CP-014 dropped (Muller no umlaut)"    "$OUT" "CP-014"
not_has    "T10 CP-015 dropped (Siemens GmbH)"        "$OUT" "CP-015"
not_has    "T11 CP-016 dropped (Siemens AG variant)"  "$OUT" "CP-016"
has        "T12 CP-011 kept (Volkswagen, no dup)"     "$OUT" "CP-011"
has        "T13 CP-012 kept (Allianz, no dup)"        "$OUT" "CP-012"

# ── Group 2: init_counterparties.py — canonical ───────────────────────────────

echo ""
echo "── init_counterparties.py  method=canonical ──"

OUT_CAN="$TMP/cp_can.csv"
runs_ok  "T14 canonical runs without error" \
    init_counterparties.py "$SOURCE_CSV" --output "$OUT_CAN" --method canonical

# canonical misses 'Muller' (no umlaut) vs 'Müller' — keeps 8 not 7
check_rows "T15 canonical keeps 8 records (Muller not caught)" "$OUT_CAN" 8
has        "T16 CP-014 kept by canonical (Muller missed)"      "$OUT_CAN" "CP-014"
not_has    "T17 CP-002 still dropped by canonical"             "$OUT_CAN" "CP-002"
not_has    "T18 CP-006 still dropped by canonical"             "$OUT_CAN" "CP-006"

# ── Group 3: init_counterparties.py — ignore.csv ─────────────────────────────

echo ""
echo "── init_counterparties.py  with ignore.csv ──"

IGNORE="$TMP/ignore.csv"
# Commerzbank/Commerz Bank have no other duplicates — ignoring this one pair keeps both
printf 'ID_1;ID_2\nCP-005;CP-006\n' > "$IGNORE"

OUT_IGN="$TMP/cp_ign.csv"
runs_ok  "T19 init with ignore runs without error" \
    init_counterparties.py "$SOURCE_CSV" --output "$OUT_IGN" --ignore "$IGNORE"

check_rows "T20 8 records kept when CP-005/CP-006 pair ignored" "$OUT_IGN" 8
has     "T21 CP-005 kept"                                    "$OUT_IGN" "CP-005"
has     "T22 CP-006 kept (pair ignored, both survive)"       "$OUT_IGN" "CP-006"

# ── Group 4: load_new_counterparties.py — canonical (default) ─────────────────

echo ""
echo "── load_new_counterparties.py  method=canonical (default) ──"

EXISTING="$TMP/cp_tri.csv"   # use the clean 7-record file from T01
OK="$TMP/ok_can.csv"
ERR="$TMP/err_can.csv"

runs_ok  "T22 load canonical runs without error" \
    load_new_counterparties.py "$NEW_CSV" \
        --existing "$EXISTING" --ok-output "$OK" --errors-output "$ERR"

check_rows "T23 4 OK records"            "$OK"  4
check_rows "T24 6 possible-error rows"   "$ERR" 6

has     "T25 NCP-001 flagged (Deutsche Bank GmbH)"           "$ERR" "NCP-001"
has     "T26 NCP-002 flagged (Müller Maschinenbau AG)"        "$ERR" "NCP-002"
has     "T27 NCP-004 flagged (Siemens GmbH)"                  "$ERR" "NCP-004"
has     "T28 NCP-005 flagged (Schmitt & Co. — 0.945 score)"  "$ERR" "NCP-005"
has     "T29 NCP-006 flagged (Volkswagen GmbH)"               "$ERR" "NCP-006"
has     "T30 NCP-009 flagged (Allianz SE — exact dup)"        "$ERR" "NCP-009"

has     "T31 NCP-007 in OK (BMW AG — new company)"            "$OK"  "NCP-007"
has     "T32 NCP-008 in OK (Thyssen Krupp — new company)"     "$OK"  "NCP-008"
has     "T33 NCP-010 in OK (ING NL — different country)"      "$OK"  "NCP-010"

# canonical misses the phonetic variant 'Kommerz Bank'
has     "T34 NCP-003 in OK (Kommerz Bank — canonical misses)" "$OK"  "NCP-003"
not_has "T35 NCP-003 not in errors with canonical"            "$ERR" "NCP-003"

# possible_errors.csv must have exist_ prefixed columns
has     "T36 exist_NM_CP column present in errors"            "$ERR" "exist_NM_CP"
has     "T37 overall_score column present in errors"          "$ERR" "overall_score"

# ── Group 5: load_new_counterparties.py — trigram ─────────────────────────────

echo ""
echo "── load_new_counterparties.py  method=trigram ──"

OK_TRI="$TMP/ok_tri.csv"
ERR_TRI="$TMP/err_tri.csv"

runs_ok  "T38 load trigram runs without error" \
    load_new_counterparties.py "$NEW_CSV" \
        --existing "$EXISTING" --ok-output "$OK_TRI" --errors-output "$ERR_TRI" \
        --method trigram

check_rows "T39 trigram: 3 OK records (one fewer than canonical)" "$OK_TRI"  3
check_rows "T40 trigram: 7 possible-error rows"                   "$ERR_TRI" 7

has     "T41 NCP-003 flagged by trigram (Kommerz Bank)"  "$ERR_TRI" "NCP-003"
not_has "T42 NCP-003 not in OK with trigram"             "$OK_TRI"  "NCP-003"

# ── Group 6: load_new_counterparties.py — ignore.csv ─────────────────────────

echo ""
echo "── load_new_counterparties.py  with ignore.csv ──"

IGNORE2="$TMP/ignore2.csv"
printf 'ID_1;ID_2\nNCP-001;CP-001\n' > "$IGNORE2"

OK_IGN2="$TMP/ok_ign2.csv"
ERR_IGN2="$TMP/err_ign2.csv"

runs_ok  "T43 load with ignore runs without error" \
    load_new_counterparties.py "$NEW_CSV" \
        --existing "$EXISTING" --ok-output "$OK_IGN2" --errors-output "$ERR_IGN2" \
        --ignore "$IGNORE2"

has        "T44 NCP-001 now in OK (pair NCP-001/CP-001 ignored)"  "$OK_IGN2"  "NCP-001"
not_has    "T45 NCP-001 not in errors"                            "$ERR_IGN2" "NCP-001"
check_rows "T46 5 possible-error rows (one ignored)"              "$ERR_IGN2" 5

# ── Group 7: threshold edge case ─────────────────────────────────────────────

echo ""
echo "── threshold edge case ──"

OK_THR="$TMP/ok_thr.csv"
ERR_THR="$TMP/err_thr.csv"

runs_ok  "T47 high threshold 0.99 runs without error" \
    load_new_counterparties.py "$NEW_CSV" \
        --existing "$EXISTING" --ok-output "$OK_THR" --errors-output "$ERR_THR" \
        --threshold 0.99

# NCP-005 Schmitt & Co. scores 0.945 → passes through at threshold 0.99
has     "T48 NCP-005 in OK at threshold=0.99 (score 0.945)"  "$OK_THR"  "NCP-005"
not_has "T49 NCP-005 not in errors at threshold=0.99"         "$ERR_THR" "NCP-005"

# ── Summary ───────────────────────────────────────────────────────────────────

echo ""
echo "──────────────────────────────────────────"
printf   "  Results:  %d passed,  %d failed\n" "$PASS" "$FAIL"
echo "──────────────────────────────────────────"
echo ""

[ "$FAIL" -eq 0 ]

#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

PASS=0
FAIL=0
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

ok()   { echo "  OK  $1"; PASS=$((PASS+1)); }
fail() { echo "FAIL  $1"; FAIL=$((FAIL+1)); }

echo "=== Regression test ==="

# ── Setup ───────────────────────────────────────────────────────────────────
mkdir -p "$TMPDIR/input" "$TMPDIR/output/pass1" "$TMPDIR/output/pass2"
cp "$SCRIPT_DIR/committed"/duns_company_*.json "$TMPDIR/input/"
# duns_company_350575093 appears twice (intentional duplicate — versioning test)
cp "$SCRIPT_DIR/to_be_extracted.csv" "$TMPDIR/"

# ── Pass 1 ──────────────────────────────────────────────────────────────────
python3 "$SCRIPT_DIR/run.py" "$TMPDIR"

ARCHIVE="$TMPDIR/output/pass1/archive.csv"
[ -f "$ARCHIVE" ] && ok "pass1: archive.csv created" || fail "pass1: archive.csv created"

ROWS=$(python3 -c "
import csv
with open('$ARCHIVE', encoding='utf-8-sig') as f:
    print(sum(1 for _ in csv.DictReader(f, delimiter=';')))
")
[ "$ROWS" -eq 5 ] && ok "pass1: 5 rows in archive (incl. 1 duplicate)" || fail "pass1: 5 rows in archive (got $ROWS)"

COMMITTED=$(ls "$TMPDIR/committed"/duns_company_*.json 2>/dev/null | wc -l)
[ "$COMMITTED" -eq 5 ] && ok "pass1: 5 files committed" || fail "pass1: 5 files committed (got $COMMITTED)"

[ "$(ls "$TMPDIR/input"/*.json 2>/dev/null | wc -l)" -eq 0 ] \
    && ok "pass1: input dir empty after run" \
    || fail "pass1: input dir empty after run"

# ── Pass 2 ──────────────────────────────────────────────────────────────────
"$SCRIPT_DIR/pass2.sh" "$TMPDIR"

EXTRACTED="$TMPDIR/output/pass2/extracted.csv"
[ -f "$EXTRACTED" ] && ok "pass2: extracted.csv created" || fail "pass2: extracted.csv created"

ROWS2=$(python3 -c "
import csv
with open('$EXTRACTED', encoding='utf-8-sig') as f:
    print(sum(1 for _ in csv.DictReader(f, delimiter=';')))
")
[ "$ROWS2" -eq 5 ] && ok "pass2: 5 rows in extracted (incl. 1 duplicate)" || fail "pass2: 5 rows in extracted (got $ROWS2)"

# Known-value checks
python3 << EOF
import csv, sys
rows = []
with open('$EXTRACTED', encoding='utf-8-sig') as f:
    for r in csv.DictReader(f, delimiter=';'):
        rows.append(r)

def get(duns, col):
    for r in rows:
        if r['duns_number'] == duns:
            return r.get(col, '<missing>')
    return '<missing>'

checks = [
    ('350575093', 'company_name', 'Test No 3 mining enterprise'),
    ('350575093', 'country',      'SE'),
    ('350575093', 'town',         'Umeå'),
    ('350575101', 'company_name', 'Test Tourism bank'),
    ('350575101', 'legal_form',   'LIMITED_COMPANY'),
    ('350575119', 'town',         'Gävle'),
    ('350575119', 'is_headquarter', 'True'),
    ('354394793', 'reg_number',   '5561234567'),
    ('354394793', 'street',       'Rosenborgsgatan 4-6'),
    ('354394793', 'postal_code',  '16974'),
]
failed = 0
for duns, col, expected in checks:
    got = get(duns, col)
    if got == expected:
        print(f'  OK  {duns}.{col}')
    else:
        print(f'FAIL  {duns}.{col}: expected={expected!r} got={got!r}')
        failed += 1

dup_count = sum(1 for r in rows if r['duns_number'] == '350575093')
if dup_count == 2:
    print('  OK  350575093 appears twice (versioning preserved)')
else:
    print(f'FAIL  350575093 should appear twice, got {dup_count}')
    failed += 1

sys.exit(failed)
EOF
FIELD_RESULT=$?
if [ "$FIELD_RESULT" -eq 0 ]; then
    PASS=$((PASS+10))
else
    FAIL=$((FAIL+10))
fi

# ── Unit tests ───────────────────────────────────────────────────────────────
python3 -m pytest "$SCRIPT_DIR/tests/" -q --tb=short 2>&1 | tail -3
[ "${PIPESTATUS[0]}" -eq 0 ] && ok "unit tests" || fail "unit tests"

# ── Summary ──────────────────────────────────────────────────────────────────
echo "==="
echo "Result: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1

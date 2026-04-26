#!/usr/bin/env bash
# run_tests.sh — full test suite for annex_bista.py
# Run from anywhere:  bash bista_v2/tests/run_tests.sh
# Requires: python3, pytest  (pip3 install pytest)
set -euo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$TESTS_DIR")"
FIXTURES="$TESTS_DIR/fixtures"
SCRIPT="$PROJECT_DIR/annex_bista.py"
OUTPUT_DIR="$PROJECT_DIR/output"
MELDER="$PROJECT_DIR/config/melder.json"
PERIOD="2026-03"

mkdir -p "$OUTPUT_DIR"

PASS=0; FAIL=0
ok()   { echo "  PASS  $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL  $1"; FAIL=$((FAIL + 1)); }
run_test() { local name="$1"; shift; if "$@" 2>/dev/null; then ok "$name"; else fail "$name"; fi; }

# ── T01: Files present ────────────────────────────────────────────────────────
echo ""; echo "════════════════════════════════════════"; echo " BISTA v2 smoke tests  (period $PERIOD)"; echo "════════════════════════════════════════"
echo ""; echo "── T01: Files present"
run_test "annex_bista.py"               test -f "$SCRIPT"
run_test "config/melder.json"           test -f "$MELDER"
run_test "bista_fields.csv"            test -f "$PROJECT_DIR/bista_fields.csv"
run_test "bista_calcs.csv"             test -f "$PROJECT_DIR/bista_calcs.csv"
run_test "fixtures/minimal_input.csv"  test -f "$FIXTURES/minimal_input.csv"
run_test "fixtures/full_cc_example.csv" test -f "$FIXTURES/full_cc_example.csv"
run_test "fixtures/balance_mismatch.csv" test -f "$FIXTURES/balance_mismatch.csv"

# ── T02: Minimal run ──────────────────────────────────────────────────────────
echo ""; echo "── T02: Minimal run"
MINIMAL_OUT="$OUTPUT_DIR/smoke_minimal_${PERIOD}.xml"
set +e
python3 "$SCRIPT" --input "$FIXTURES/minimal_input.csv" --period "$PERIOD" \
    --output "$MINIMAL_OUT" --melder "$MELDER" --stufe Test \
    > "$OUTPUT_DIR/smoke_minimal.log" 2>&1
MINIMAL_EXIT=$?
set -e
[[ $MINIMAL_EXIT -eq 0 ]] && ok "script exits 0 on minimal input" || fail "script exits 0 on minimal input"

# ── T03: XML content ──────────────────────────────────────────────────────────
echo ""; echo "── T03: XML content"
if [[ $MINIMAL_EXIT -eq 0 ]]; then
    run_test "output file created"             test -f "$MINIMAL_OUT"
    run_test "well-formed XML"                 bash -c "python3 -c \"import xml.etree.ElementTree as ET; ET.parse('$MINIMAL_OUT')\""
    run_test "LIEFERUNG-BISTA root"            bash -c "grep -q 'LIEFERUNG-BISTA' '$MINIMAL_OUT'"
    run_test "FORMULAR HV"                     bash -c "grep -q 'name=\"HV\"' '$MINIMAL_OUT'"
    run_test "FORMULAR B7"                     bash -c "grep -q 'name=\"B7\"' '$MINIMAL_OUT'"
    run_test "FORMULAR L1"                     bash -c "grep -q 'name=\"L1\"' '$MINIMAL_OUT'"
    run_test "stufe=Test"                      bash -c "grep -q 'stufe=\"Test\"' '$MINIMAL_OUT'"
    run_test "period $PERIOD"                  bash -c "grep -q '$PERIOD' '$MINIMAL_OUT'"
    run_test "Z071S11 (HV11/071 encoding)"     bash -c "grep -q 'pos=\"Z071S11\"' '$MINIMAL_OUT'"
    run_test "Z122S02 (B7 convenience credit)" bash -c "grep -q 'pos=\"Z122S02\"' '$MINIMAL_OUT'"
    run_test "B7 col01 absent in B7 formular (revolving=0)" \
        python3 -c "
import xml.etree.ElementTree as ET
NS='http://www.bundesbank.de/xmw/2003-01-01'
root=ET.parse('$MINIMAL_OUT').getroot()
b7=[f for fm in root.iter(f'{{{NS}}}FORMULAR') if fm.attrib.get('name')=='B7'
    for f in fm.iter(f'{{{NS}}}FELD') if f.attrib['pos'].endswith('S01')]
exit(1 if b7 else 0)"
else
    for t in "output file created" "well-formed XML" "LIEFERUNG-BISTA root" "FORMULAR HV" \
             "FORMULAR B7" "FORMULAR L1" "stufe=Test" "period" "Z071S11" "Z122S02" "Z122S01 absent"; do
        fail "$t (skipped — script failed)"
    done
fi

# ── T04: Reconciliation ───────────────────────────────────────────────────────
echo ""; echo "── T04: Reconciliation"
if [[ $MINIMAL_EXIT -eq 0 ]] && [[ -f "$MINIMAL_OUT" ]]; then
    run_test "minimal input passes recon" bash -c "python3 '$TESTS_DIR/check_reconciliation.py' '$MINIMAL_OUT'"
else
    fail "reconciliation (skipped)"
fi

# ── T05: Balance mismatch detected ────────────────────────────────────────────
echo ""; echo "── T05: Mismatch detection"
MISMATCH_OUT="$OUTPUT_DIR/smoke_mismatch_${PERIOD}.xml"
set +e
python3 "$SCRIPT" --input "$FIXTURES/balance_mismatch.csv" --period "$PERIOD" \
    --output "$MISMATCH_OUT" --melder "$MELDER" > /dev/null 2>&1
set -e
[[ -f "$MISMATCH_OUT" ]] && \
    run_test "mismatch rejected by recon" bash -c "! python3 '$TESTS_DIR/check_reconciliation.py' '$MISMATCH_OUT'" || \
    fail "mismatch test skipped"

# ── T06: Full CC example ──────────────────────────────────────────────────────
echo ""; echo "── T06: Full CC example"
FULL_OUT="$OUTPUT_DIR/smoke_full_${PERIOD}.xml"
set +e
python3 "$SCRIPT" --input "$FIXTURES/full_cc_example.csv" --period "$PERIOD" \
    --output "$FULL_OUT" --melder "$MELDER" > "$OUTPUT_DIR/smoke_full.log" 2>&1
FULL_EXIT=$?
set -e
if [[ $FULL_EXIT -eq 0 ]]; then
    ok "full CC example exits 0"
    run_test "A1 formular present"              bash -c "grep -q 'name=\"A1\"' '$FULL_OUT'"
    run_test "A2 formular present"              bash -c "grep -q 'name=\"A2\"' '$FULL_OUT'"
    run_test "B3 formular present"              bash -c "grep -q 'name=\"B3\"' '$FULL_OUT'"
    run_test "C1 formular present"              bash -c "grep -q 'name=\"C1\"' '$FULL_OUT'"
    run_test "Z114S02 (B7 corporations col02)"  bash -c "grep -q 'pos=\"Z114S02\"' '$FULL_OUT'"
    run_test "B7 col01 absent from B7 (revolving=0)" \
        python3 -c "
import xml.etree.ElementTree as ET
NS='http://www.bundesbank.de/xmw/2003-01-01'
root=ET.parse('$FULL_OUT').getroot()
b7=[f for fm in root.iter(f'{{{NS}}}FORMULAR') if fm.attrib.get('name')=='B7'
    for f in fm.iter(f'{{{NS}}}FELD') if f.attrib['pos'].endswith('S01')]
exit(1 if b7 else 0)"
else
    fail "full CC example exits 0 (see output/smoke_full.log)"
fi

# ── T07: Golden file (opt-in) ─────────────────────────────────────────────────
echo ""; echo "── T07: Golden file"
GOLDEN="$FIXTURES/minimal_expected.xml"
if [[ -f "$GOLDEN" ]] && [[ $MINIMAL_EXIT -eq 0 ]]; then
    if command -v xmllint &>/dev/null; then
        run_test "output matches golden" \
            bash -c "diff <(xmllint --c14n '$MINIMAL_OUT' 2>/dev/null) <(xmllint --c14n '$GOLDEN' 2>/dev/null) > /dev/null"
    else
        echo "  SKIP  xmllint not installed"
    fi
else
    echo "  SKIP  no golden file  (run: cp $MINIMAL_OUT $GOLDEN  to bless)"
fi

# ── pytest suite ──────────────────────────────────────────────────────────────
echo ""; echo "════════════════════════════════════════"; echo " pytest suite"; echo "════════════════════════════════════════"
if python3 -m pytest --version &>/dev/null 2>&1; then
    set +e
    python3 -m pytest "$TESTS_DIR" --ignore="$TESTS_DIR/fixtures" --tb=short -q 2>&1
    PYTEST_EXIT=$?
    set -e
    [[ $PYTEST_EXIT -eq 0 ]] && ok "pytest suite passed" || fail "pytest suite failed"
else
    echo "  SKIP  pytest not installed — pip3 install pytest"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""; echo "════════════════════════════════════════"
TOTAL=$((PASS + FAIL))
echo " Results: $PASS/$TOTAL passed,  $FAIL failed"
echo "════════════════════════════════════════"; echo ""
[[ $FAIL -eq 0 ]]

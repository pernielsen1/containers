#!/usr/bin/env bash
# run_tests.sh — regression test suite for annex_bista.py
# Run from anywhere: bash bista_v2/tests/run_tests.sh
set -euo pipefail

# ── Paths ─────────────────────────────────────────────────────────────────────
TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$TESTS_DIR")"
FIXTURES="$TESTS_DIR/fixtures"
SCRIPT="$PROJECT_DIR/annex_bista.py"
OUTPUT_DIR="$PROJECT_DIR/output"
MELDER="$PROJECT_DIR/config/melder.json"
PERIOD="2026-03"
TEST_OUTPUT="$OUTPUT_DIR/test_minimal_${PERIOD}.xml"

mkdir -p "$OUTPUT_DIR"

# ── Helpers ───────────────────────────────────────────────────────────────────
PASS=0; FAIL=0

ok()   { echo "  PASS  $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL  $1"; FAIL=$((FAIL + 1)); }

run_test() {
    local name="$1"; shift
    if "$@" 2>/dev/null; then ok "$name"; else fail "$name"; fi
}

# ── Test definitions ──────────────────────────────────────────────────────────

echo ""
echo "════════════════════════════════════════════"
echo " BISTA v2 regression tests  (period $PERIOD)"
echo "════════════════════════════════════════════"

# T01: script exists and is executable
echo ""
echo "── T01: Infrastructure"
run_test "script file exists"     test -f "$SCRIPT"
run_test "config/melder.json exists" test -f "$MELDER"
run_test "fixtures/minimal_input.csv exists" test -f "$FIXTURES/minimal_input.csv"
run_test "input/example.csv exists" test -f "$PROJECT_DIR/input/example.csv"

# T02: script runs without crashing on minimal input
echo ""
echo "── T02: Script execution"
run_test "script is runnable by python3" \
    bash -c "python3 '$SCRIPT' --help > /dev/null"

# Capture exit code without aborting the test suite
set +e
python3 "$SCRIPT" \
    --input  "$FIXTURES/minimal_input.csv" \
    --period "$PERIOD" \
    --output "$TEST_OUTPUT" \
    --melder "$MELDER" \
    --stufe  Test \
    > "$OUTPUT_DIR/test_run.log" 2>&1
SCRIPT_EXIT=$?
set -e

if [[ $SCRIPT_EXIT -eq 0 ]]; then
    ok "script exits 0 on minimal input"
else
    fail "script exits 0 on minimal input  (exit=$SCRIPT_EXIT — see output/test_run.log)"
fi

# T03: output file checks (only run if script succeeded)
echo ""
echo "── T03: Output file"
if [[ $SCRIPT_EXIT -eq 0 ]]; then
    run_test "output XML file created" test -f "$TEST_OUTPUT"

    # Valid XML (python xml.etree will error on malformed XML)
    run_test "output is well-formed XML" \
        bash -c "python3 -c \"import xml.etree.ElementTree as ET; ET.parse('$TEST_OUTPUT')\" 2>/dev/null"

    # Root element
    run_test "root element is LIEFERUNG-BISTA" \
        bash -c "grep -q 'LIEFERUNG-BISTA' '$TEST_OUTPUT'"

    # Required FORMULARs present
    run_test "FORMULAR HV present" \
        bash -c "grep -q 'name=\"HV\"' '$TEST_OUTPUT'"
    run_test "FORMULAR B7 present" \
        bash -c "grep -q 'name=\"B7\"' '$TEST_OUTPUT'"
    run_test "FORMULAR L1 present" \
        bash -c "grep -q 'name=\"L1\"' '$TEST_OUTPUT'"

    # Stufe is Test
    run_test "stufe=Test in output" \
        bash -c "grep -q 'stufe=\"Test\"' '$TEST_OUTPUT'"

    # Period
    run_test "reporting period $PERIOD in output" \
        bash -c "grep -q '$PERIOD' '$TEST_OUTPUT'"
else
    for t in "output XML file created" \
             "output is well-formed XML" \
             "root element is LIEFERUNG-BISTA" \
             "FORMULAR HV present" \
             "FORMULAR B7 present" \
             "FORMULAR L1 present" \
             "stufe=Test in output" \
             "reporting period $PERIOD in output"; do
        fail "$t  (skipped — script did not run)"
    done
fi

# T04: reconciliation checks (run via python helper when script is ready)
echo ""
echo "── T04: Reconciliation (requires script implementation)"
if [[ $SCRIPT_EXIT -eq 0 ]] && [[ -f "$TEST_OUTPUT" ]]; then
    # HV11/180 = HV21/330 (balance sheet balances)
    run_test "balance sheet balances (HV11/180 = HV21/330)" \
        bash -c "python3 '$TESTS_DIR/check_reconciliation.py' '$TEST_OUTPUT' 2>/dev/null"
else
    fail "balance sheet balances  (skipped — no output)"
fi

# T05: golden file comparison (opt-in once a blessed output exists)
echo ""
echo "── T05: Golden file"
GOLDEN="$FIXTURES/minimal_expected.xml"
if [[ -f "$GOLDEN" ]] && [[ $SCRIPT_EXIT -eq 0 ]]; then
    run_test "output matches golden file" \
        bash -c "diff <(xmllint --c14n '$TEST_OUTPUT' 2>/dev/null) \
                      <(xmllint --c14n '$GOLDEN'     2>/dev/null) > /dev/null"
else
    echo "  SKIP  golden file comparison  (run: cp $TEST_OUTPUT $GOLDEN  to bless)"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════"
TOTAL=$((PASS + FAIL))
echo " Results: $PASS/$TOTAL passed,  $FAIL failed"
echo "════════════════════════════════════════════"
echo ""

[[ $FAIL -eq 0 ]]   # exit 1 if any failures

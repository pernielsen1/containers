#!/usr/bin/env bash
# run_tests.sh — full test suite for kresta.py
# Run from anywhere:  bash kresta/tests/run_tests.sh
set -euo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$TESTS_DIR")"
FIXTURES="$TESTS_DIR/fixtures"
SCRIPT="$PROJECT_DIR/kresta.py"
OUTPUT_DIR="$PROJECT_DIR/output"
MELDER="$PROJECT_DIR/config/melder.json"
PERIOD="2026-03"

mkdir -p "$OUTPUT_DIR"

PASS=0; FAIL=0
ok()   { echo "  PASS  $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL  $1"; FAIL=$((FAIL + 1)); }
run_test() { local name="$1"; shift; if "$@" 2>/dev/null; then ok "$name"; else fail "$name"; fi; }

# ── T01: Files present ────────────────────────────────────────────────────────
echo ""; echo "════════════════════════════════════════"; echo " KreStA smoke tests  (period $PERIOD)"; echo "════════════════════════════════════════"
echo ""; echo "── T01: Files present"
run_test "kresta.py"                    test -f "$SCRIPT"
run_test "config/melder.json"           test -f "$MELDER"
run_test "kresta_fields.csv"           test -f "$PROJECT_DIR/kresta_fields.csv"
run_test "kresta_calcs.csv"            test -f "$PROJECT_DIR/kresta_calcs.csv"
run_test "fixtures/minimal_input.csv"  test -f "$FIXTURES/minimal_input.csv"
run_test "fixtures/full_cc_example.csv" test -f "$FIXTURES/full_cc_example.csv"

# ── T02: Minimal run ──────────────────────────────────────────────────────────
echo ""; echo "── T02: Minimal run"
MINIMAL_OUT="$OUTPUT_DIR/kresta_minimal_${PERIOD}.xml"
set +e
python3 "$SCRIPT" --input "$FIXTURES/minimal_input.csv" --period "$PERIOD" \
    --output "$MINIMAL_OUT" --melder "$MELDER" --stufe Test \
    > "$OUTPUT_DIR/kresta_minimal.log" 2>&1
MINIMAL_EXIT=$?
set -e
[[ $MINIMAL_EXIT -eq 0 ]] && ok "script exits 0 on minimal input" || fail "script exits 0 on minimal input"

# ── T03: XML content ──────────────────────────────────────────────────────────
echo ""; echo "── T03: XML content"
if [[ $MINIMAL_EXIT -eq 0 ]]; then
    run_test "output file created"           test -f "$MINIMAL_OUT"
    run_test "well-formed XML"               bash -c "python3 -c \"import xml.etree.ElementTree as ET; ET.parse('$MINIMAL_OUT')\""
    run_test "LIEFERUNG-VJKRE root"          bash -c "grep -q 'LIEFERUNG-VJKRE' '$MINIMAL_OUT'"
    run_test "stufe=Test"                    bash -c "grep -q 'stufe=\"Test\"' '$MINIMAL_OUT'"
    run_test "period $PERIOD"               bash -c "grep -q '$PERIOD' '$MINIMAL_OUT'"
    run_test "FORMULAR V1"                   bash -c "grep -q 'name=\"V1\"' '$MINIMAL_OUT'"
    run_test "Z220S01 (households non-inst)" bash -c "grep -q 'pos=\"Z220S01\"' '$MINIMAL_OUT'"
    run_test "Z200S01 derived (200=220)"     bash -c "grep -q 'pos=\"Z200S01\"' '$MINIMAL_OUT'"
    run_test "Z400S01 derived (400=200+300)" bash -c "grep -q 'pos=\"Z400S01\"' '$MINIMAL_OUT'"
    run_test "No HV formular (no BISTA merge)" bash -c "! grep -q 'name=\"HV\"' '$MINIMAL_OUT'"
else
    for t in "output file created" "well-formed XML" "LIEFERUNG-VJKRE root" "stufe=Test" \
             "period" "FORMULAR V1" "Z220S01" "Z200S01 derived" "Z400S01 derived" "No HV formular"; do
        fail "$t (skipped — script failed)"
    done
fi

# ── T04: Value check ──────────────────────────────────────────────────────────
echo ""; echo "── T04: Value encoding"
if [[ $MINIMAL_EXIT -eq 0 ]]; then
    run_test "Z220S01 = 120000 Tsd (120M EUR)" \
        python3 -c "
import xml.etree.ElementTree as ET
NS='http://www.bundesbank.de/xmw/2003-01-01'
root=ET.parse('$MINIMAL_OUT').getroot()
fields={f.attrib['pos']: int(f.text) for fm in root.iter(f'{{{NS}}}FORMULAR')
        for f in fm.iter(f'{{{NS}}}FELD')}
assert fields.get('Z220S01') == 120000, f'Got {fields.get(\"Z220S01\")}'"
    run_test "Z200S01 = 120000 (derived = Z220S01)" \
        python3 -c "
import xml.etree.ElementTree as ET
NS='http://www.bundesbank.de/xmw/2003-01-01'
root=ET.parse('$MINIMAL_OUT').getroot()
fields={f.attrib['pos']: int(f.text) for fm in root.iter(f'{{{NS}}}FORMULAR')
        for f in fm.iter(f'{{{NS}}}FELD')}
assert fields.get('Z200S01') == 120000, f'Got {fields.get(\"Z200S01\")}'"
    run_test "Z400S01 = 120000 (derived = Z100+Z200+Z300)" \
        python3 -c "
import xml.etree.ElementTree as ET
NS='http://www.bundesbank.de/xmw/2003-01-01'
root=ET.parse('$MINIMAL_OUT').getroot()
fields={f.attrib['pos']: int(f.text) for fm in root.iter(f'{{{NS}}}FORMULAR')
        for f in fm.iter(f'{{{NS}}}FELD')}
assert fields.get('Z400S01') == 120000, f'Got {fields.get(\"Z400S01\")}'"
else
    fail "value checks (skipped — script failed)"
fi

# ── T05: Full CC example ──────────────────────────────────────────────────────
echo ""; echo "── T05: Full CC example"
FULL_OUT="$OUTPUT_DIR/kresta_full_${PERIOD}.xml"
set +e
python3 "$SCRIPT" --input "$FIXTURES/full_cc_example.csv" --period "$PERIOD" \
    --output "$FULL_OUT" --melder "$MELDER" > "$OUTPUT_DIR/kresta_full.log" 2>&1
FULL_EXIT=$?
set -e
if [[ $FULL_EXIT -eq 0 ]]; then
    ok "full CC example exits 0"
    run_test "FORMULAR V1 present"     bash -c "grep -q 'name=\"V1\"' '$FULL_OUT'"
    run_test "FORMULAR V2 present"     bash -c "grep -q 'name=\"V2\"' '$FULL_OUT'"
    run_test "FORMULAR V1B present"    bash -c "grep -q 'name=\"V1B\"' '$FULL_OUT'"
    run_test "No FORMULAR V3 (no long-term)" bash -c "! grep -q 'name=\"V3\"' '$FULL_OUT'"
    run_test "Z100S01 derived (enterprises total)" bash -c "grep -q 'pos=\"Z100S01\"' '$FULL_OUT'"
    run_test "Z400S01 derived (grand total)" bash -c "grep -q 'pos=\"Z400S01\"' '$FULL_OUT'"
else
    fail "full CC example exits 0 (see output/kresta_full.log)"
fi

# ── T06: Stufe Produktion ─────────────────────────────────────────────────────
echo ""; echo "── T06: Stufe"
PROD_OUT="$OUTPUT_DIR/kresta_prod_${PERIOD}.xml"
set +e
python3 "$SCRIPT" --input "$FIXTURES/minimal_input.csv" --period "$PERIOD" \
    --output "$PROD_OUT" --melder "$MELDER" --stufe Produktion > /dev/null 2>&1
set -e
[[ -f "$PROD_OUT" ]] && \
    run_test "stufe=Produktion in XML" bash -c "grep -q 'stufe=\"Produktion\"' '$PROD_OUT'" || \
    fail "stufe Produktion test skipped"

# ── pytest suite ──────────────────────────────────────────────────────────────
echo ""; echo "════════════════════════════════════════"; echo " pytest suite"; echo "════════════════════════════════════════"
if python3 -m pytest --version &>/dev/null 2>&1; then
    set +e
    python3 -m pytest "$TESTS_DIR" --ignore="$TESTS_DIR/fixtures" --tb=short -q 2>&1
    PYTEST_EXIT=$?
    set -e
    [[ $PYTEST_EXIT -eq 0 ]] && ok "pytest suite passed" || fail "pytest suite failed"
else
    echo "  SKIP  pytest not installed"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""; echo "════════════════════════════════════════"
TOTAL=$((PASS + FAIL))
echo " Results: $PASS/$TOTAL passed,  $FAIL failed"
echo "════════════════════════════════════════"; echo ""
[[ $FAIL -eq 0 ]]

# BISTA v2 — Design Summary

**Scope**: Monthly Balance Sheet Statistics (Monatliche Bilanzstatistik) annex-level reporting
**Legal basis**: ECB Regulation ECB/2021/2, Guideline ECB/2021/11
**Guidelines version used**: Deutsche Bundesbank Banking Statistics Guidelines, January 2026 (unofficial English translation)

---

## Business Profile

A German-licensed MFI that is a **charge card company only**:
- Issues charge cards to **households and enterprises**
- Cardholders are **domestic, other euro area (EA), and non-EA foreign**
- **No revolving credit** — full balance due at end of each billing cycle
- No savings deposits, no securities issuance, no derivatives
- **Not subject to ECB minimum reserve requirements**
- Funded via interbank borrowing + equity

---

## Annex Selection

### Mandatory for this business

| Annex | Content | Why |
|-------|---------|-----|
| **HV11/HV12** | Assets main form + supplements | Always required |
| **HV21/HV22** | Liabilities main form + supplements | Always required |
| **B1** | Loans to non-banks — domestic + non-EA foreign, sector × maturity | Card receivables core breakdown |
| **B3** | Loans to non-banks — other EA member states (same structure as B1) | Cross-border EA cardholders present |
| **B4** | Household loans by type (consumer / housing / other) | Household cards issued; receivables = "other loans" |
| **B7** | Credit card credit — convenience vs extended, by sector | The specialist card annex; convenience only, no revolving |
| **L1** | Irrevocable lending commitments by sector | Unused card limits are irrevocable off-balance commitments |

### Conditional (likely but small)

| Annex | Condition |
|-------|-----------|
| **A1** | If liquidity placed with banks (overnight, time deposits) |
| **A2** | If funded via interbank borrowing |
| **C1** | If customers overpay cards — credit balances = on-demand liability |
| **C3** | Same as C1 but for EA non-bank counterparties |
| **C5** | If C1 overnight balances are freely transferable on demand |

### Confirmed NIL

A3, B6, BA, C2, C4, D1, D2, E1–E5, F1, F2, H1, H2, I1, I2, M1, M2, O1, O2, P1, Q1, S1

---

## Key Reporting Decisions

### B7 — Credit card credit
- Charge card balance at month-end = **convenience credit card credit** (column 01)
- Extended/revolving credit (column 02) = always zero — explicitly omit from XML
- B7 covers **domestic + EA** counterparties only; non-EA foreign stays in B1 alone
- B7 domestic total must reconcile with B1 domestic sector rows
- B7 EA total must reconcile with B3 sector rows

### B4 — Household loan type
- Charge card receivables to households classified as **"other loans"** (not consumer instalment, not housing)
- B4 covers domestic + EA households **combined** (unlike B1/B3 which separate them)
- B4 total must equal B1 household rows + B3 household rows

### L1 — Irrevocable lending commitments
- = **unused portion** of each card limit at month-end (total granted limit minus outstanding balance)
- Off-balance sheet — reported via HV21/390 and broken down in L1 by sector
- L1 total must equal HV21/390

### C1/C3 — Credit balances on card accounts
- Per guidelines: overpayments by cardholders create a liability classified as **"on demand"** (column 01)
- Typically small but must be captured monthly

---

## CSV Input Format

File: `input/your_file.csv`
Encoding: UTF-8 with BOM (`utf-8-sig`)
Separator: comma

```
form,line,column,description,value_eur,comments
```

| Field | Notes |
|-------|-------|
| `form` | `HV11` / `HV12` / `HV21` / `HV22` for main form; `A1` / `B1` / `B7` / `L1` etc. for annexes |
| `line` | Numeric row code from official Bundesbank form template (e.g. `300` = domestic households in B1) |
| `column` | `00` for single-value main-form items; `01`–`nn` for annex column dimension |
| `description` | Free text — not used by script, for human readability |
| `value_eur` | Full EUR amount; script converts to EUR thousands for XML |
| `comments` | Free text — ignored by script |

Lines starting with `#` and blank lines are ignored. Zero values are omitted from XML output (nil by omission per XMW spec).

See `input/example.csv` for a fully annotated charge card company example.

---

## XML Position Encoding

| Form | Encoding | Example |
|------|----------|---------|
| HV11 | `Z{line}S11` | item 071 → `Z071S11` |
| HV12 | `Z{line}S12` | item 178 → `Z178S12` |
| HV21 | `Z{line}S21` | item 390 → `Z390S21` |
| HV22 | `Z{line}S22` | item 510 → `Z510S22` |
| Any annex | `Z{line}S{column}` | B7/line 300/col 01 → `Z300S01` |

All HV11/12/21/22 items are emitted in a single `<FORMULAR name="HV">`.
Each annex gets its own `<FORMULAR name="B7">` etc.

> **⚠ Open item**: The annex encoding `Z{line}S{column}` is a logical extrapolation of the main form pattern — not yet verified against a live Bundesbank XMW file. Verification requires one ExtraNet sample XML containing an annex. The fix, if needed, is confined to `encode_pos()` in `annex_bista.py`.

---

## Key Reconciliation Rules

| Rule | Check |
|------|-------|
| Balance sheet balances | `HV11/180` == `HV21/330` |
| L1 total = commitments header | sum(L1 all fields) == `HV21/390` |
| B7 domestic = B1 domestic card rows | B7 domestic sector total == B1/200 + B1/300 (for pure card company) |
| B4 households = B1 + B3 households | B4/213 == B1/300 + B3/300 |
| B1 + B3 + non-EA = card receivables | (B1 + B3 + B1 non-EA rows) == `HV11/071` |

---

## Script Usage

```bash
# Standard run (Test mode, default output path)
python3 annex_bista.py --input input/example.csv --period 2026-03

# Specify output and go live
python3 annex_bista.py \
    --input  input/example.csv \
    --period 2026-03 \
    --output output/bista_2026-03.xml \
    --melder config/melder.json \
    --stufe  Produktion

# Run regression tests
bash tests/run_tests.sh

# Bless a new golden file after first good run
cp output/test_minimal_2026-03.xml tests/fixtures/minimal_expected.xml
```

---

## Project Structure

```
bista_v2/
├── annex_bista.py          Main script: CSV → XMW XML
├── bista_v2.md             This document
├── config/
│   └── melder.json         Reporting institution config (BLZ, name, address, contact, RZLZ)
├── input/
│   └── example.csv         Fully annotated charge card company example
├── output/                 Generated XML files (not committed)
└── tests/
    ├── fixtures/
    │   ├── minimal_input.csv       Smallest valid test case
    │   └── minimal_expected.xml    Golden file (created after first blessed run)
    ├── check_reconciliation.py     Validates balance sheet + L1 vs HV21/390
    └── run_tests.sh                Regression suite (15 tests; run from anywhere)
```

---

## Reference

| Document | URL |
|----------|-----|
| Banking Statistics Guidelines Jan 2026 | https://www.bundesbank.de/resource/blob/620158/4f3806b49ca5b2bbcdb492e0d728d3a1/472B63F073F071307366337C94F8C870/statso01-03-monatliche-bilanzstatistik-data.pdf |
| Bundesbank BISTA reporting page | https://www.bundesbank.de/en/service/reporting-systems/banking-statistics/monthly-balance-sheet-statistics-620110 |
| Submission format | XMW XML via ExtraNet (NExt from Q3 2026) |
| Deadline | 6th business day after end of reporting month |

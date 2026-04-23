# Design discussion — duplicate_v2 (2026-04-23)

## Problem

Two scripts needed for continuous AnaCredit counterparty data hygiene:

1. **init_counterparties.py** — bootstrap a clean `counterparties.csv` from
   `test_counterparties.csv` by removing duplicates (keep first of each group).

2. **load_new_counterparties.py** — validate incoming records before loading:
   split into `OK_new_counterparties.csv` (safe to load) and
   `possible_errors.csv` (needs human review).

---

## Approaches considered

### A — Trigram (character n-gram) similarity
Split normalized names into overlapping 3-character windows.
Score pairs with Jaccard coefficient on the trigram sets.
Naturally handles abbreviations, compound-word splits, umlauts.
No external dependencies beyond the standard library.

### B — Sorted neighborhood
Sort all records by a normalized key, slide a window of width W,
score only pairs within the window.  O(n·W) — scales to large files.
Window size is a tuning parameter; records far apart in sort order
are never compared.

### C — Multiple canonical forms + exact lookup
Generate 3–4 normalized variants per name (strip legal suffix,
expand umlauts, sort tokens, 5-char prefix).  Store existing records
in a dict keyed by every variant.  Lookup is O(1) per record.
Binary candidate / no-candidate; no graded recall.

---

## Decision

- **Trigram (A)** as `--method trigram` — wider net, better for the init pass
  where we want high recall.
- **Canonical (C)** as `--method canonical` — fast and deterministic,
  better for the repeated load pass where speed and explainability matter.

Both methods are available in both scripts via `--method`.
Scoring after candidate generation uses `difflib.SequenceMatcher`
(standard library) weighted across name, city, street, postal, country.

---

## ignore.csv

Semicolon-delimited file with header `ID_1;ID_2`.
Each row is a pair of CNTRPRTY_IDs that have been reviewed and
confirmed as **not** duplicates.  Both scripts accept `--ignore ignore.csv`
(silently skipped if the file does not exist).

**Workflow intention:** review `possible_errors.csv`, copy false-positive
pairs into `ignore.csv`, re-run.  As data quality improves, raise
`--threshold` toward 1.0 ("zero tolerance").

---

## Typical workflow

```bash
# First pass — cast a wide net
python init_counterparties.py test_counterparties.csv --method trigram --threshold 0.65

# Review output, populate ignore.csv with confirmed non-duplicates

# Re-run with ignore list, tighten threshold as data improves
python init_counterparties.py test_counterparties.csv --method trigram \
    --threshold 0.75 --ignore ignore.csv

# Load new data — fast canonical check
python load_new_counterparties.py new_counterparties.csv \
    --method canonical --ignore ignore.csv
```

---

## Output formats

### possible_errors.csv
One row per (new record, matching existing record) pair.
Column order: all columns from the new record first, then all columns
from the matched existing record each prefixed with `exist_`
(e.g. `exist_NM_CP`), then `overall_score`.

### ignore.csv
```
ID_1;ID_2
CP-007;CP-008
CP-001;CP-013
```

---

## Implementation (2026-04-23)

### Files created

| File | Purpose |
|---|---|
| `duplicate_utils.py` | Shared module — normalization, candidate generation, scoring, union-find, ignore loading |
| `init_counterparties.py` | Script 1 — deduplicates source CSV, keeps first of each group |
| `load_new_counterparties.py` | Script 2 — cross-matches new records against existing |
| `new_counterparties.csv` | Test input for the load script (10 records) |
| `regression/test.sh` | 50 regression tests; run with `bash regression/test.sh` from `duplicate_v2/` |

### Scoring function (both methods)

`difflib.SequenceMatcher` weighted across fields — no external dependencies:

| Field | Weight |
|---|---|
| Name | 55% |
| City | 20% |
| Street | 10% |
| Postal code | 10% |
| Country | 5% |

Candidate generation differs between methods; scoring is identical so
`overall_score` values are directly comparable across `--method` runs.

---

## Bug found and fixed during regression testing

`_pairs_from_canonical_index` in `duplicate_utils.py` used loop counter
indices (`records[i]`) instead of the stored record indices
(`records[members[i]]`).  This caused it to compare entirely wrong record
pairs — most scored below threshold and were silently discarded, but some
accidents passed through (e.g. Müller/Mueller was found by coincidence
via the Siemens group having 4 members, making range(4) reach index 2 and 3).

**Fix:** `a, b = records[members[i]], records[members[j]]`

The trigram method did not have this bug (it stores record indices as dict
keys before the lookup step).

---

## Observed method difference on test data

Running `init_counterparties.py` against `test_counterparties.csv` (16 records):

| Method | Records kept | Notes |
|---|---|---|
| trigram | 7 | Catches "Muller" (no umlaut) vs "Müller" via shared trigrams |
| canonical | 8 | Misses "Muller" — normalized forms don't overlap after umlaut expansion |

CP-014 "Muller Maschinenbau KG" is the specific record canonical misses.
Documented in regression tests T15/T16.

---

## Test file: new_counterparties.csv

10 records covering the main scenarios:

| ID | Name | Scenario | canonical result | trigram result |
|---|---|---|---|---|
| NCP-001 | Deutsche Bank GmbH | Same name, different legal form | error | error |
| NCP-002 | Müller Maschinenbau AG | Umlaut variant, different suffix | error | error |
| NCP-003 | Kommerz Bank AG | Phonetic variant of Commerzbank | **OK** | error |
| NCP-004 | Siemens GmbH | Different suffix, same address | error | error |
| NCP-005 | Schmitt & Co. GmbH | Name typo + different suffix (score 0.945) | error | error |
| NCP-006 | Volkswagen GmbH | Different suffix, same address | error | error |
| NCP-007 | BMW AG | Completely new company | OK | OK |
| NCP-008 | Thyssen Krupp AG | Completely new company | OK | OK |
| NCP-009 | Allianz SE | Exact duplicate | error | error |
| NCP-010 | ING Bank NV | Different country | OK | OK |

NCP-003 is intentionally kept in the test file to document the
canonical/trigram trade-off: canonical is precise, trigram casts a wider net.

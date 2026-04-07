# find_duplicates skill

Find possible duplicate counterparties in an AnaCredit counterparty CSV using
phonetic name matching (NYSIIS + Jaro-Winkler) and address similarity.

## What this skill does

Runs `find_duplicates.py` against a counterparty CSV and produces a wide-format
output CSV: one row per source record with each possible duplicate in its own
`dup1_*`, `dup2_*`, … column group.

## Step 1 — Locate the script

The canonical script is at:
```
~/containers/claude_exp/find_duplicates/find_duplicates.py
```

Check that it exists:
```bash
ls ~/containers/claude_exp/find_duplicates/find_duplicates.py
```

If missing, tell the user and stop.

## Step 2 — Check dependency

```bash
python3 -c "import jellyfish" 2>/dev/null || pip3 install jellyfish --break-system-packages -q
```

## Step 3 — Determine input file

If the user provided a file path as an argument to the skill, use that.
Otherwise ask: "Which counterparty CSV file should I check for duplicates?"

The input CSV must be semicolon-delimited, UTF-8-BOM, and contain these columns:
`CNTRPRTY_ID`, `NM_CP`, `ADDRS_STRT`, `CITY`, `PSTL_CD`, `CNTRY`

## Step 4 — Run

```bash
python3 ~/containers/claude_exp/find_duplicates/find_duplicates.py <input_file> \
    --output <input_file_stem>_duplicates.csv \
    [--threshold 0.70]
```

Default threshold is 0.70. If the user specified a threshold, pass it via `--threshold`.

## Step 5 — Report results

After the run, print a brief summary to the user:
- Number of records read
- Number of records flagged with at least one duplicate
- Number of records with 2+ duplicates
- Output file path

If no duplicates were found, say so and suggest lowering the threshold.

## Output format

Each output row represents one source counterparty with its possible duplicates
in separate column groups:

| Columns | Content |
|---------|---------|
| `src_id` … `src_country` | Source counterparty (6 fields) |
| `dup_count` | Number of possible duplicates found |
| `dup1_id` … `dup1_confidence` | Best-scoring duplicate (9 fields) |
| `dup2_id` … `dup2_confidence` | Second-best duplicate, if any (9 fields) |
| … | Further duplicates if present |

Confidence levels: **HIGH** (≥ 0.90), **MEDIUM** (≥ 0.78), **LOW** (≥ 0.70)

## Usage

```
/find_duplicates
/find_duplicates data/counterparties.csv
/find_duplicates data/counterparties.csv --threshold 0.80
```

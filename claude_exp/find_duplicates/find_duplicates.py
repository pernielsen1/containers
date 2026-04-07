#!/usr/bin/env python3
"""
find_duplicates.py — Phonetic duplicate detection for AnaCredit counterparty data

Reads a semicolon-delimited UTF-8-BOM CSV of counterparty records and writes a
wide-format CSV: one row per source record that has at least one possible duplicate,
with each duplicate in its own set of columns (dup1_*, dup2_*, …).

Algorithm:
  1. Normalize names (expand umlauts, strip legal suffixes, lowercase)
  2. Encode with NYSIIS phonetic algorithm (jellyfish)
  3. Group records by two strategies:
       a) NYSIIS of first token — phonetic variants within one word
       b) 4-char name prefix   — compound-word splits (e.g. "commerzbank" vs "commerz bank")
  4. Score each candidate pair: name Jaro-Winkler (55%) + city (20%) + street (10%)
                                 + postal code (10%) + country match (5%)
  5. For each record with score >= threshold, collect all duplicates sorted by score desc
  6. Write one row per source record; each duplicate occupies its own dupN_* columns

Columns expected in input CSV:
  CNTRPRTY_ID, NM_CP, ADDRS_STRT, CITY, PSTL_CD, CNTRY

Requirements:
  pip3 install jellyfish

Usage:
  python3 find_duplicates.py input.csv [--output duplicates.csv] [--threshold 0.70]
"""

import csv
import sys
import re
import argparse
from itertools import combinations
from collections import defaultdict

try:
    import jellyfish
except ImportError:
    sys.exit("ERROR: jellyfish not installed. Run: pip3 install jellyfish")

# ── Column names ──────────────────────────────────────────────────────────────

COL_ID      = "CNTRPRTY_ID"
COL_NAME    = "NM_CP"
COL_STREET  = "ADDRS_STRT"
COL_CITY    = "CITY"
COL_POSTAL  = "PSTL_CD"
COL_COUNTRY = "CNTRY"

REQUIRED_COLS = [COL_ID, COL_NAME, COL_STREET, COL_CITY, COL_POSTAL, COL_COUNTRY]

# ── Normalization helpers ─────────────────────────────────────────────────────

_UMLAUT = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue",
    "Ä": "AE", "Ö": "OE", "Ü": "UE",
    "ß": "ss",
    "à": "a", "á": "a", "â": "a", "ã": "a", "å": "a",
    "è": "e", "é": "e", "ê": "e", "ë": "e",
    "ì": "i", "í": "i", "î": "i", "ï": "i",
    "ò": "o", "ó": "o", "ô": "o", "õ": "o",
    "ù": "u", "ú": "u", "û": "u",
    "ñ": "n", "ç": "c",
})

_LEGAL_SUFFIX = re.compile(
    r"\b("
    r"gmbh\s*&\s*co\.?\s*kg"
    r"|gmbh\s*co\s*kg"
    r"|gmbh|ag|kg|ohg|gbr|se|ug|mbh"
    r"|e\.?\s*v\.?"
    r"|ltd|llc|inc|corp|plc"
    r"|sa|sas|srl|bv|nv|ab|as|oy|spa|sarl"
    r")\b",
    re.IGNORECASE,
)

_STREET_ABBREVS = [
    (re.compile(r"\bstr\.\b",  re.I), "strasse"),
    (re.compile(r"\bstraße\b", re.I), "strasse"),
    (re.compile(r"\bstr\b",    re.I), "strasse"),
    (re.compile(r"\bpl\.\b",   re.I), "platz"),
    (re.compile(r"\ballee\b",  re.I), "allee"),
    (re.compile(r"\bweg\b",    re.I), "weg"),
]

def _clean(s: str) -> str:
    s = s.lower().translate(_UMLAUT)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def normalize_name(name: str) -> str:
    s = name.lower().translate(_UMLAUT)
    s = _LEGAL_SUFFIX.sub("", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def normalize_street(street: str) -> str:
    s = street.lower().translate(_UMLAUT)
    for pattern, repl in _STREET_ABBREVS:
        s = pattern.sub(repl, s)
    return _clean(s)

def normalize_city(city: str) -> str:
    return _clean(city)

def phonetic_key(name: str) -> str:
    """NYSIIS encoding of the first meaningful token of the normalized name."""
    for t in normalize_name(name).split():
        if len(t) >= 2:
            return jellyfish.nysiis(t)
    return ""

def prefix_key(name: str) -> str:
    """First 4 characters of the normalized name.
    Catches compound-word splits: 'commerzbank' vs 'commerz bank'."""
    n = normalize_name(name)
    return n[:4] if len(n) >= 4 else n

# ── Scoring ───────────────────────────────────────────────────────────────────

def _jw(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return jellyfish.jaro_winkler_similarity(a, b)

def score_pair(a: dict, b: dict) -> dict:
    name_s   = _jw(normalize_name(a[COL_NAME]),     normalize_name(b[COL_NAME]))
    city_s   = _jw(normalize_city(a[COL_CITY]),     normalize_city(b[COL_CITY]))
    street_s = _jw(normalize_street(a[COL_STREET]), normalize_street(b[COL_STREET]))

    same_country = a[COL_COUNTRY] == b[COL_COUNTRY]
    if not same_country:
        postal_s = 0.0
    elif a[COL_POSTAL] == b[COL_POSTAL]:
        postal_s = 1.0
    elif a[COL_POSTAL][:3] == b[COL_POSTAL][:3]:
        postal_s = 0.7
    else:
        postal_s = 0.0

    country_s = 1.0 if same_country else 0.0

    overall = (
        0.55 * name_s
        + 0.20 * city_s
        + 0.10 * street_s
        + 0.10 * postal_s
        + 0.05 * country_s
    )

    confidence = "HIGH" if overall >= 0.90 else ("MEDIUM" if overall >= 0.78 else "LOW")

    return {
        "name_score":    round(name_s,    4),
        "city_score":    round(city_s,    4),
        "street_score":  round(street_s,  4),
        "postal_score":  round(postal_s,  4),
        "country_match": int(country_s),
        "overall_score": round(overall,   4),
        "confidence":    confidence,
    }

# ── Candidate generation ──────────────────────────────────────────────────────

def _candidate_pairs(records: list) -> list:
    """Return deduplicated candidate pairs from two grouping strategies."""
    seen: set = set()
    candidates = []

    def add_from_groups(groups: dict) -> None:
        for group in groups.values():
            for a, b in combinations(group, 2):
                key = tuple(sorted([a[COL_ID], b[COL_ID]]))
                if key not in seen:
                    seen.add(key)
                    candidates.append((a, b))

    nysiis_groups: dict = defaultdict(list)
    for rec in records:
        k = phonetic_key(rec[COL_NAME])
        if k:
            nysiis_groups[k].append(rec)
    add_from_groups(nysiis_groups)

    prefix_groups: dict = defaultdict(list)
    for rec in records:
        k = prefix_key(rec[COL_NAME])
        if k:
            prefix_groups[k].append(rec)
    add_from_groups(prefix_groups)

    return candidates

# ── Wide-format output builder ────────────────────────────────────────────────

def build_wide_rows(records: list, threshold: float) -> tuple:
    """
    For each record with at least one duplicate above threshold, build one output row.
    Duplicates are sorted by overall_score descending and placed in dup1_*, dup2_*, …
    columns.  Both A→B and B→A appear (symmetric), so a data steward sees every
    record's own perspective.

    Returns (rows, max_dups_per_record).
    """
    id_to_rec = {r[COL_ID]: r for r in records}

    # adjacency: id → [(scores_dict, candidate_record), …]
    adj: dict = defaultdict(list)

    for a, b in _candidate_pairs(records):
        scores = score_pair(a, b)
        if scores["overall_score"] >= threshold:
            adj[a[COL_ID]].append((scores, b))
            adj[b[COL_ID]].append((scores, a))

    # Deduplicate within each list (safety) and sort best score first
    for src_id in adj:
        seen_cands: set = set()
        deduped = []
        for scores, rec in adj[src_id]:
            if rec[COL_ID] not in seen_cands:
                seen_cands.add(rec[COL_ID])
                deduped.append((scores, rec))
        adj[src_id] = sorted(deduped, key=lambda x: x[0]["overall_score"], reverse=True)

    max_dups = max((len(v) for v in adj.values()), default=0)

    rows = []
    for src_id, dup_list in adj.items():
        src = id_to_rec[src_id]
        row: dict = {
            "src_id":      src[COL_ID],
            "src_name":    src[COL_NAME],
            "src_street":  src[COL_STREET],
            "src_city":    src[COL_CITY],
            "src_postal":  src[COL_POSTAL],
            "src_country": src[COL_COUNTRY],
            "dup_count":   len(dup_list),
        }
        for i, (scores, dup) in enumerate(dup_list, 1):
            p = f"dup{i}_"
            row[f"{p}id"]            = dup[COL_ID]
            row[f"{p}name"]          = dup[COL_NAME]
            row[f"{p}street"]        = dup[COL_STREET]
            row[f"{p}city"]          = dup[COL_CITY]
            row[f"{p}postal"]        = dup[COL_POSTAL]
            row[f"{p}country"]       = dup[COL_COUNTRY]
            row[f"{p}name_score"]    = scores["name_score"]
            row[f"{p}overall_score"] = scores["overall_score"]
            row[f"{p}confidence"]    = scores["confidence"]
        rows.append(row)

    # Sort: most duplicates first, then by best score
    rows.sort(key=lambda r: (-r["dup_count"], -r.get("dup1_overall_score", 0)))
    return rows, max_dups

# ── I/O ───────────────────────────────────────────────────────────────────────

def _output_columns(max_dups: int) -> list:
    cols = ["src_id", "src_name", "src_street", "src_city", "src_postal", "src_country",
            "dup_count"]
    for i in range(1, max_dups + 1):
        p = f"dup{i}_"
        cols += [f"{p}id", f"{p}name", f"{p}street", f"{p}city",
                 f"{p}postal", f"{p}country",
                 f"{p}name_score", f"{p}overall_score", f"{p}confidence"]
    return cols

def read_csv(path: str) -> list:
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        rows = list(reader)
        missing = [c for c in REQUIRED_COLS if c not in (reader.fieldnames or [])]
    if missing:
        sys.exit(f"ERROR: Input CSV is missing required columns: {missing}")
    return rows

def write_csv(path: str, rows: list, max_dups: int) -> None:
    cols = _output_columns(max_dups)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cols, delimiter=";",
                                extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows(rows)

# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Find duplicate counterparties using phonetic + similarity matching"
    )
    parser.add_argument("input",  help="Input CSV (semicolon-delimited, utf-8-sig)")
    parser.add_argument("--output",    default="duplicates_found.csv",
                        help="Output CSV path (default: duplicates_found.csv)")
    parser.add_argument("--threshold", type=float, default=0.70,
                        help="Overall score threshold (default: 0.70)")
    args = parser.parse_args()

    records = read_csv(args.input)
    rows, max_dups = build_wide_rows(records, args.threshold)

    if rows:
        write_csv(args.output, rows, max_dups)

    total_pairs = sum(r["dup_count"] for r in rows) // 2  # each pair counted twice
    high   = sum(1 for r in rows if r.get("dup1_confidence") == "HIGH")
    medium = sum(1 for r in rows if r.get("dup1_confidence") == "MEDIUM")
    low    = sum(1 for r in rows if r.get("dup1_confidence") == "LOW")
    multi  = sum(1 for r in rows if r["dup_count"] > 1)

    print(f"Records read:                {len(records)}")
    print(f"Records with duplicates:     {len(rows)}")
    print(f"Unique duplicate pairs:      {total_pairs}")
    print(f"  Records w/ 1 duplicate:    {len(rows) - multi}")
    print(f"  Records w/ 2+ duplicates:  {multi}")
    print(f"  Best-match HIGH  (>= 0.90):{high}")
    print(f"  Best-match MEDIUM(>= 0.78):{medium}")
    print(f"  Best-match LOW   (>= 0.70):{low}")
    print(f"Max duplicates per record:   {max_dups}")
    print(f"Output columns:              src(6) + dup_count + {max_dups}x dup(9) = "
          f"{7 + max_dups * 9} total")
    print(f"Output:                      {args.output}")

    return 1 if rows else 0


if __name__ == "__main__":
    sys.exit(main())

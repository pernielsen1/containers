"""
duplicate_utils.py — shared duplicate-detection logic for init_counterparties
and load_new_counterparties.

Two candidate-generation strategies are available:

  trigram   — character trigram inverted index; wide recall, handles
               abbreviations, compound-word splits, umlaut variants.

  canonical — multiple normalized forms (full name, first token, sorted
               tokens, 5-char prefix); fast exact lookup, deterministic,
               easy to explain.

Both strategies feed into the same SequenceMatcher-based scorer so
overall_score values are directly comparable across methods.
"""

import csv
import re
from collections import defaultdict
from difflib import SequenceMatcher

# ── Column names ──────────────────────────────────────────────────────────────

COL_ID      = "CNTRPRTY_ID"
COL_NAME    = "NM_CP"
COL_STREET  = "ADDRS_STRT"
COL_CITY    = "CITY"
COL_POSTAL  = "PSTL_CD"
COL_COUNTRY = "CNTRY"

REQUIRED_COLS = [COL_ID, COL_NAME, COL_STREET, COL_CITY, COL_POSTAL, COL_COUNTRY]

# ── Normalization ─────────────────────────────────────────────────────────────

_UMLAUT = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue",
    "Ä": "ae", "Ö": "oe", "Ü": "ue",
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
    r"gmbh\s*&\s*co\.?\s*kg|gmbh\s*co\s*kg"
    r"|gmbh|ag|kg|ohg|gbr|se|ug|mbh"
    r"|e\.?\s*v\.?"
    r"|ltd|llc|inc|corp|plc"
    r"|sa|sas|srl|bv|nv|ab|as|oy|spa|sarl"
    r"|und\s+co|& co"
    r")\b\.?",
    re.IGNORECASE,
)

_STREET_ABBREVS = [
    (re.compile(r"\bstraße\b",  re.I), "strasse"),
    (re.compile(r"\bstr\.\b",   re.I), "strasse"),
    (re.compile(r"\bstr\b",     re.I), "strasse"),
    (re.compile(r"\bpl\.\b",    re.I), "platz"),
]


def _scrub(s: str) -> str:
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_name(name: str) -> str:
    s = name.lower().translate(_UMLAUT)
    s = _LEGAL_SUFFIX.sub(" ", s)
    return _scrub(s)


def normalize_street(street: str) -> str:
    s = street.lower().translate(_UMLAUT)
    for pat, repl in _STREET_ABBREVS:
        s = pat.sub(repl, s)
    return _scrub(s)


def normalize_city(city: str) -> str:
    return _scrub(city.lower().translate(_UMLAUT))


# ── Scoring ───────────────────────────────────────────────────────────────────

def _sim(a: str, b: str) -> float:
    """SequenceMatcher similarity ratio (0–1)."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def score_pair(a: dict, b: dict) -> float:
    """Weighted similarity score for a record pair (0–1)."""
    name_s   = _sim(normalize_name(a[COL_NAME]),     normalize_name(b[COL_NAME]))
    city_s   = _sim(normalize_city(a[COL_CITY]),     normalize_city(b[COL_CITY]))
    street_s = _sim(normalize_street(a[COL_STREET]), normalize_street(b[COL_STREET]))

    same_country = a[COL_COUNTRY].strip() == b[COL_COUNTRY].strip()
    if not same_country:
        postal_s = 0.0
    elif a[COL_POSTAL].strip() == b[COL_POSTAL].strip():
        postal_s = 1.0
    elif a[COL_POSTAL].strip()[:3] == b[COL_POSTAL].strip()[:3]:
        postal_s = 0.7
    else:
        postal_s = 0.0

    return round(
        0.55 * name_s
        + 0.20 * city_s
        + 0.10 * street_s
        + 0.10 * postal_s
        + 0.05 * (1.0 if same_country else 0.0),
        4,
    )


# ── Trigram helpers ───────────────────────────────────────────────────────────

_MIN_SHARED_TRIGRAMS = 2


def _trigrams(s: str) -> set:
    if len(s) < 3:
        return {s} if s else set()
    return {s[i:i+3] for i in range(len(s) - 2)}


def _trigram_index(records: list) -> dict:
    """trigram → [record_index, ...]"""
    idx: dict = defaultdict(list)
    for i, rec in enumerate(records):
        for tg in _trigrams(normalize_name(rec[COL_NAME])):
            idx[tg].append(i)
    return idx


def _pairs_from_trigram_index(records: list, idx: dict) -> list:
    """Return (rec_a, rec_b) candidate pairs sharing >= _MIN_SHARED_TRIGRAMS."""
    shared: dict = defaultdict(int)
    for members in idx.values():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                shared[(members[i], members[j])] += 1

    seen: set = set()
    pairs = []
    for (i, j), count in shared.items():
        if count >= _MIN_SHARED_TRIGRAMS:
            a, b = records[i], records[j]
            key = (min(a[COL_ID], b[COL_ID]), max(a[COL_ID], b[COL_ID]))
            if key not in seen:
                seen.add(key)
                pairs.append((a, b))
    return pairs


# ── Canonical-form helpers ────────────────────────────────────────────────────

_MIN_CANONICAL_LEN = 4


def _canonical_forms(name: str) -> set:
    n = normalize_name(name)
    tokens = n.split()
    forms: set = set()
    if len(n) >= _MIN_CANONICAL_LEN:
        forms.add(n)
        forms.add(n[:5])
    if tokens:
        if len(tokens[0]) >= _MIN_CANONICAL_LEN:
            forms.add(tokens[0])
        sorted_key = " ".join(sorted(tokens))
        if len(sorted_key) >= _MIN_CANONICAL_LEN:
            forms.add(sorted_key)
    return forms


def _canonical_index(records: list) -> dict:
    """canonical_form → [record_index, ...]"""
    idx: dict = defaultdict(list)
    for i, rec in enumerate(records):
        for form in _canonical_forms(rec[COL_NAME]):
            idx[form].append(i)
    return idx


def _pairs_from_canonical_index(records: list, idx: dict) -> list:
    seen: set = set()
    pairs = []
    for members in idx.values():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = records[members[i]], records[members[j]]
                key = (min(a[COL_ID], b[COL_ID]), max(a[COL_ID], b[COL_ID]))
                if key not in seen:
                    seen.add(key)
                    pairs.append((a, b))
    return pairs


# ── Union-Find ────────────────────────────────────────────────────────────────

def build_group_ids(pairs: list) -> dict:
    """
    Union-Find over a list of (id_a, id_b) pairs.
    Returns {id: group_root} where the root is the lexicographically smallest id
    in each connected component.
    """
    parent: dict = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx == ry:
            return
        if rx < ry:
            parent[ry] = rx
        else:
            parent[rx] = ry

    for a_id, b_id in pairs:
        union(a_id, b_id)

    return {x: find(x) for x in parent}


# ── Ignore list ───────────────────────────────────────────────────────────────

def load_ignore(path: str) -> set:
    """
    Load ignore.csv (semicolon-delimited, header ID_1;ID_2).
    Returns a set of frozensets so pair order doesn't matter.
    Silently returns empty set if the file doesn't exist.
    """
    ignore: set = set()
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f, delimiter=";")
            next(reader, None)  # skip header
            for row in reader:
                row = [c.strip() for c in row]
                if len(row) >= 2 and row[0] and row[1]:
                    ignore.add(frozenset([row[0], row[1]]))
    except FileNotFoundError:
        pass
    return ignore


def is_ignored(id_a: str, id_b: str, ignore_set: set) -> bool:
    return frozenset([id_a, id_b]) in ignore_set


# ── Public API ────────────────────────────────────────────────────────────────

def find_duplicate_pairs(
    records: list,
    method: str,
    threshold: float,
    ignore_set: set,
) -> list:
    """
    Find duplicate pairs within a single list of records.
    Returns [(rec_a, rec_b, score), ...] sorted by score descending.
    """
    if method == "trigram":
        idx = _trigram_index(records)
        candidates = _pairs_from_trigram_index(records, idx)
    else:
        idx = _canonical_index(records)
        candidates = _pairs_from_canonical_index(records, idx)

    result = []
    for a, b in candidates:
        if is_ignored(a[COL_ID], b[COL_ID], ignore_set):
            continue
        s = score_pair(a, b)
        if s >= threshold:
            result.append((a, b, s))

    result.sort(key=lambda t: -t[2])
    return result


def find_cross_pairs(
    new_records: list,
    existing_records: list,
    method: str,
    threshold: float,
    ignore_set: set,
) -> list:
    """
    Find pairs where one record is from new_records and one from existing_records.
    Returns [(new_rec, exist_rec, score), ...] sorted by score descending.
    """
    if method == "trigram":
        exist_idx = _trigram_index(existing_records)
        # For each new record, count shared trigrams with each existing record
        result_pairs = []
        seen: set = set()
        for new_rec in new_records:
            shared: dict = defaultdict(int)
            for tg in _trigrams(normalize_name(new_rec[COL_NAME])):
                for ei in exist_idx.get(tg, []):
                    shared[ei] += 1
            for ei, count in shared.items():
                if count >= _MIN_SHARED_TRIGRAMS:
                    exist_rec = existing_records[ei]
                    key = (new_rec[COL_ID], exist_rec[COL_ID])
                    if key not in seen:
                        seen.add(key)
                        result_pairs.append((new_rec, exist_rec))
    else:
        exist_idx = _canonical_index(existing_records)
        result_pairs = []
        seen = set()
        for new_rec in new_records:
            for form in _canonical_forms(new_rec[COL_NAME]):
                for ei in exist_idx.get(form, []):
                    exist_rec = existing_records[ei]
                    key = (new_rec[COL_ID], exist_rec[COL_ID])
                    if key not in seen:
                        seen.add(key)
                        result_pairs.append((new_rec, exist_rec))

    result = []
    for new_rec, exist_rec in result_pairs:
        if is_ignored(new_rec[COL_ID], exist_rec[COL_ID], ignore_set):
            continue
        s = score_pair(new_rec, exist_rec)
        if s >= threshold:
            result.append((new_rec, exist_rec, s))

    result.sort(key=lambda t: -t[2])
    return result


# ── CSV I/O ───────────────────────────────────────────────────────────────────

def read_csv(path: str, required_cols: list = None) -> tuple:
    """Returns (rows, fieldnames). Raises ValueError on missing required columns."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    if required_cols:
        missing = [c for c in required_cols if c not in fieldnames]
        if missing:
            raise ValueError(f"{path}: missing columns {missing}")
    return rows, fieldnames


def write_csv(path: str, rows: list, fieldnames: list) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=fieldnames, delimiter=";",
            extrasaction="ignore", restval="",
        )
        writer.writeheader()
        writer.writerows(rows)

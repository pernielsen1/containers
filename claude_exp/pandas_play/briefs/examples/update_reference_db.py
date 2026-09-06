#!/usr/bin/env python3
"""
Example 3: a second, independently-updating SQLite database.

Scenario: "entries" + "load_batches" (example_multi.db) get reloaded
every time a new CSV batch lands -- frequent, transactional. A
key -> category/owner reference table changes rarely (someone tweaks
an ownership mapping now and then), so it lives in its OWN database
file, refreshed on its own schedule, independent of the entries loads.

This script only UPSERTs into reference.db -- it never touches
example_multi.db. It "refreshes" twice, from two versions of the
source CSV, to show that unchanged rows are left alone (no new
updated_at) while changed/new rows are.

Run: python3 update_reference_db.py
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from csv_typing import read_all_str_csv

HERE = Path(__file__).parent
REF_DB_PATH = HERE / "reference.db"

conn = sqlite3.connect(REF_DB_PATH)
conn.execute("""
    CREATE TABLE IF NOT EXISTS key_reference (
        key         TEXT PRIMARY KEY,
        category    TEXT,
        owner       TEXT,
        updated_at  TEXT NOT NULL
    )
""")


def upsert_reference(csv_path):
    df = read_all_str_csv(csv_path)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    before = conn.total_changes
    for row in df.itertuples(index=False):
        # ON CONFLICT ... DO UPDATE with a WHERE clause: only touch the
        # row (and bump updated_at) if something actually changed.
        # IS NOT (rather than !=) so this stays correct even if
        # category/owner is legitimately NULL for some key.
        conn.execute("""
            INSERT INTO key_reference (key, category, owner, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                category   = excluded.category,
                owner      = excluded.owner,
                updated_at = excluded.updated_at
            WHERE key_reference.category IS NOT excluded.category
               OR key_reference.owner    IS NOT excluded.owner
        """, (row.key, row.category, row.owner, now))
    conn.commit()
    touched = conn.total_changes - before
    print(f"{csv_path.name}: {len(df)} rows read, {touched} inserted/updated (unchanged rows skipped)")


upsert_reference(HERE / "sample_reference.csv")

print()
print("After first refresh:")
for r in conn.execute("SELECT * FROM key_reference ORDER BY key"):
    print(r)

print()
# a later refresh: K003's category changed, K005's owner changed, K009
# is brand new -- K001/K002/K007 are identical in both files.
upsert_reference(HERE / "sample_reference_v2.csv")

print()
print("After second refresh (only changed/new rows got a new updated_at):")
for r in conn.execute("SELECT * FROM key_reference ORDER BY key"):
    print(r)

conn.close()

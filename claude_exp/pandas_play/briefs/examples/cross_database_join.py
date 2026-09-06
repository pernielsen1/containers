#!/usr/bin/env python3
"""
Example 4: joining across two SQLite database files.

example_multi.db (entries, load_batches) and reference.db
(key_reference) update on different schedules, so they're kept as
separate files rather than tables in one database. SQLite's
ATTACH DATABASE lets you query across both without merging them.

Run this after multi_table_example.py and update_reference_db.py
have both created their respective .db files.

Run: python3 cross_database_join.py
"""
import sqlite3
from pathlib import Path

HERE = Path(__file__).parent
MAIN_DB = HERE / "example_multi.db"
REF_DB = HERE / "reference.db"

conn = sqlite3.connect(MAIN_DB)
conn.execute("ATTACH DATABASE ? AS ref", (str(REF_DB),))

print("Latest batch's entries, joined with the (independently updated) reference table:")
for r in conn.execute("""
    SELECT e.key, e.num_value, e.the_date, r.category, r.owner
    FROM main.entries e
    LEFT JOIN ref.key_reference r ON r.key = e.key
    WHERE e.batch_id = (SELECT MAX(batch_id) FROM main.load_batches)
    ORDER BY e.key
"""):
    print(r)
print()

print("Entries with no matching reference row yet (category/owner would be NULL):")
for r in conn.execute("""
    SELECT e.key
    FROM main.entries e
    LEFT JOIN ref.key_reference r ON r.key = e.key
    WHERE e.batch_id = (SELECT MAX(batch_id) FROM main.load_batches)
      AND r.key IS NULL
    ORDER BY e.key
"""):
    print(r)
print()

print("Reference keys that have never shown up in any entries batch:")
for r in conn.execute("""
    SELECT r.key, r.category, r.owner
    FROM ref.key_reference r
    LEFT JOIN main.entries e ON e.key = r.key
    WHERE e.key IS NULL
    ORDER BY r.key
"""):
    print(r)

conn.execute("DETACH DATABASE ref")
conn.close()

#!/usr/bin/env python3
"""
who_am_i.py — Portable Claude Code memory seed for Per Nielsen's containers.

Usage:
    python3 who_am_i.py            # print identity summary
    python3 who_am_i.py --seed     # seed memory into current project
    python3 who_am_i.py --dry-run  # show what would be written without writing

Drop this file into any new container and run it to restore full working context
in Claude Code for that project directory.

No external dependencies — stdlib only.
Designed for deployment in regulated environments (banking).
"""

import argparse
import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Embedded memory content
# Each entry: (filename, frontmatter_dict, body)
# ---------------------------------------------------------------------------

MEMORY_FILES: list[tuple[str, dict, str]] = [
    (
        "user_environment.md",
        {
            "name": "user_environment",
            "description": "Runtime environment details for this user's sandbox (Python command, shell, etc.)",
            "type": "user",
        },
        """\
Python is invoked as `python3`, not `python`, on this system (WSL).
Always use `python3` in scripts, shell commands, and examples.
""",
    ),
    (
        "feedback_csv_encoding.md",
        {
            "name": "CSV encoding preference",
            "description": "User prefers semicolon-delimited UTF-8 CSVs over Excel files",
            "type": "feedback",
        },
        """\
Always use semicolon (`;`) as CSV separator and `utf-8-sig` encoding for all CSV output files.

**Why:** Semicolons avoid conflicts with decimal commas — this user's CSVs use `,` as the decimal
separator (European convention). utf-8-sig (UTF-8 with BOM) preserves international characters
(ü, ä, ö etc.) when opened in Excel. An attempt to generate Excel (.xlsx) output was made but
deemed not successful — user explicitly chose CSV-only.

**How to apply:** Any time a script writes CSV output, use `delimiter=";"` and `encoding="utf-8-sig"`.
When parsing numeric values from CSVs, treat `,` as the decimal separator (e.g. `1.234,56` = 1234.56).
Do not offer Excel as an alternative output format unless explicitly asked.
""",
    ),
    (
        "project_anacredit.md",
        {
            "name": "AnaCredit project",
            "description": (
                "Context, files, and approach for AnaCredit data extraction "
                "and validation (ECB credit register, Deutsche Bundesbank)"
            ),
            "type": "project",
        },
        """\
AnaCredit is an ECB credit register reporting framework. The user works with AnaCredit guidelines
in a banking context (Deutsche Bundesbank). All work is in `/home/perni/containers/AnaCredit/`.

## Source documents
- `docs/anacredit-guidelines-data.pdf` — ECB AnaCredit reporting guidelines (English),
  chapters 4–5 cover datasets and data attributes
- `docs/anacredit-codelist-version-2-8-data.xlsx` — authoritative reference for coded values
  (1,087 legal form codes); always prefer over any PDF URLs
- `docs/anacredit-handbuch-validierungsregeln-version-22-data.pdf` — Bundesbank validation rules
  handbook (German), v22 valid from 2026-08-01; section 4.1 = RI rules, 4.2 = completeness
  (CY0010–CY0220), 4.4 = consistency (CN_ prefix), 4.5 = postal code formats (130 countries)

## Scripts
- `src/validate_counterparty.py` — field-level validator: completeness, consistency, postal codes;
  loads all codelists from JSON at startup
- `src/validate_cp_xref.py` — cross-reference validator: RI0140_DE / RI0150_DE / RI0160_DE
  (head office, immediate parent, ultimate parent must exist as counterparties);
  uses `(id, id_type)` tuple matching
- `src/postal_code_validator.py` — standalone `PostalCodeValidator` class; 130-country regex
  rules from `codelists/postal_code_formats.json`
- `src/extract_attributes.py` — extracts 120 attributes from guidelines PDF → CSV
- `validate.sh` — runs both validators sequentially; exit code 1 if either finds errors

## Codelists directory (`codelists/`)
All valid-value sets are externalised to JSON — never hardcoded in Python:
`column_map.json`, `country_codes.json`, `institutional_sectors.json`,
`legal_proceeding_status.json`, `enterprise_sizes.json`, `cp_id_types.json`,
`accounting_standards.json`, `reporting_member_states.json`, `postal_code_formats.json`

## Sample data (`sample_counterparty.csv` — 7 rows)
- Row 2 (10070000): Deutsche Bank — valid; head_office self-reference → RI0140_DE OK
- Row 3 (CUST-001-VALID): Valid GmbH; no cross-refs; LEI missing → WARNING
- Row 4 (INTL0000000000001): IMF — international org, NOT_APPL on many fields
- Row 5 (CUST-ERR-001): Deliberately invalid — bad LEI, country, legal form, sector, size,
  accounting → multiple ERRORs
- Row 6 (CUST-WARN-001): head_office_id=10020000 (type=3) → references row 7 → RI0140_DE OK;
  missing dates → WARNINGs
- Row 7 (10020000): Konzern Holding GmbH — exists to satisfy CUST-WARN-001's head office reference
- Row 8 (CUST-XREF-BAD): ultimate_parent_id=GHOST-PARENT-999 → not in dataset → RI0160_DE ERROR

## How to apply
- When extending validation to other datasets, follow the same pattern: load codelists from
  JSON/Excel, use `(id, id_type)` pairs for cross-references, exit code 1 on any ERROR
- The codelist Excel is always the authoritative source for allowed coded values
- All CSVs: semicolon separator, utf-8-sig encoding, NOT_APPL sentinels
""",
    ),
]

MEMORY_INDEX_ENTRIES = [
    ("project_anacredit.md", "AnaCredit ECB credit register: validators, codelists, sample data, 120 attributes across 11 datasets"),
    ("feedback_csv_encoding.md", "All CSVs: semicolon separator, utf-8-sig encoding; no Excel output"),
    ("user_environment.md", "Python is `python3` on this system (WSL); use in all scripts/commands"),
]

IDENTITY_SUMMARY = """\
=== WHO AM I ===

USER
  Name   : Per Nielsen
  Git    : per.nielsen1@outlook.com
  Role   : Senior Architect — Python, Java, C, C++, RPG/RPGle, COBOL
  Context: Private sandbox (WSL laptop) → findings exported to regulated banking environment

ENVIRONMENT
  OS     : WSL2 (Linux on Windows)
  Python : python3  (never `python`)
  Shell  : bash

PREFERENCES
  CSV    : delimiter=';'  encoding='utf-8-sig'  decimal separator=','  (European convention)
  Output : CSV only — no Excel unless explicitly requested
  Style  : Concise responses — no trailing summaries of completed actions

ACTIVE PROJECT — AnaCredit
  Path   : /home/perni/containers/AnaCredit/
  What   : ECB credit register validator for Deutsche Bundesbank reporting
  Docs   : guidelines PDF, codelist Excel (v2.8, 1087 legal form codes),
           validation handbook (v22, valid from 2026-08-01)
  Scripts: validate_counterparty.py, validate_cp_xref.py, postal_code_validator.py,
           extract_attributes.py, validate.sh
  Rules  : codelists externalised to JSON; (id, id_type) tuples for cross-refs;
           exit code 1 on any ERROR

EXPORT PIPELINE
  sandbox → ~/containers/ → GitHub ($GIT_USER_NAME / $GIT_ACCESS_TOKEN)
===============
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def encode_cwd() -> str:
    """Encode the current working directory as a Claude project key.

    Claude encodes project paths by replacing '/' with '-'.
    Example: /home/perni/containers → -home-perni-containers
    """
    return str(Path.cwd()).replace("/", "-")


def memory_dir_for_cwd() -> Path:
    """Return the Claude memory directory for the current working directory."""
    return Path.home() / ".claude" / "projects" / encode_cwd() / "memory"


def render_memory_file(frontmatter: dict, body: str) -> str:
    """Render a memory file with YAML-ish frontmatter."""
    lines = ["---"]
    for key, value in frontmatter.items():
        # Wrap long values in quotes
        if "\n" in str(value) or len(str(value)) > 60:
            lines.append(f'{key}: "{value}"')
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append("")
    lines.append(body)
    return "\n".join(lines)


def render_memory_index() -> str:
    lines = ["# Memory Index", ""]
    for filename, hook in MEMORY_INDEX_ENTRIES:
        lines.append(f"- [{filename}]({filename}) — {hook}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def show_summary() -> None:
    print(IDENTITY_SUMMARY)


def seed_memory(dry_run: bool = False) -> None:
    target = memory_dir_for_cwd()
    print(f"Target memory directory: {target}")

    if dry_run:
        print("[dry-run] Would write the following files:")
    else:
        target.mkdir(parents=True, exist_ok=True)

    files_to_write: list[tuple[Path, str]] = []

    for filename, frontmatter, body in MEMORY_FILES:
        path = target / filename
        content = render_memory_file(frontmatter, body)
        files_to_write.append((path, content))

    index_path = target / "MEMORY.md"
    files_to_write.append((index_path, render_memory_index()))

    for path, content in files_to_write:
        if dry_run:
            print(f"  {path}")
        else:
            path.write_text(content, encoding="utf-8")
            print(f"  written: {path.name}")

    if not dry_run:
        print(f"\nMemory seeded into {target}")
        print("Restart Claude Code (or open a new session) in this directory to pick it up.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print user identity summary and optionally seed Claude Code memory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Write memory files into ~/.claude/projects/<cwd>/memory/",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what --seed would write without actually writing anything",
    )
    args = parser.parse_args()

    show_summary()

    if args.seed or args.dry_run:
        print()
        seed_memory(dry_run=args.dry_run)
    else:
        print(f"Tip: run with --seed to write memory files into this project.")
        print(f"     run with --dry-run to preview what would be written.")


if __name__ == "__main__":
    main()

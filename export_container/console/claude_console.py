#!/usr/bin/env python3
"""
AnaCredit Claude Console
========================
Interactive terminal console for AnaCredit validation assistance.
Connects to the Claude API with full AnaCredit context and exposes
the local validators as tools Claude can invoke.

Usage:
    python3 console/claude_console.py              # interactive mode
    python3 console/claude_console.py --who-am-i   # print context summary and exit
    python3 console/claude_console.py --validate <csv_file>   # run validation, then chat

Requirements:
    ANTHROPIC_API_KEY environment variable must be set.

No external dependencies beyond the anthropic package and stdlib.
"""

import argparse
import csv
import io
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("ERROR: anthropic package not installed. Run: pip install anthropic")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Paths (relative to workspace root — works both inside and outside container)
# ---------------------------------------------------------------------------

WORKSPACE = Path(__file__).parent.parent
SRC_DIR   = WORKSPACE / "src"
CODELISTS = WORKSPACE / "codelists"
DATA_DIR  = WORKSPACE / "data"

# ---------------------------------------------------------------------------
# System prompt — AnaCredit context
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert AnaCredit assistant embedded in a Deutsche Bundesbank regulatory reporting environment.

## Your role
Help the user work with AnaCredit (ECB credit register) counterparty reference data:
- Explain validation rules (from Handbuch zu den AnaCredit-Validierungsregeln, Version 22, valid from 2026-08-01)
- Interpret validation errors and warnings produced by the validators
- Advise on correct field values, codelists, and data quality
- Help write or debug Python validation scripts

## AnaCredit context
- 120 data attributes across 11 datasets; counterparty reference data has 29 attributes
- Codelists: all coded values are authoritative from anacredit-codelist-version-2-8-data.xlsx
- Validation rule categories:
    - RI rules (section 4.1): referential integrity between datasets
    - CY rules (section 4.2): completeness of counterparty attributes
    - CN rules (section 4.4): consistency between fields
    - Postal code format rules (section 4.5): 130 countries
- NOT_APPL is a valid sentinel value when a field is not applicable
- Cross-reference rules: RI0140_DE (head office), RI0150_DE (immediate parent), RI0160_DE (ultimate parent)
  must reference existing counterparties using (id, id_type) tuple matching

## Data conventions
- CSV: semicolon delimiter, utf-8-sig encoding, comma as decimal separator (European convention)
- Severity levels: ERROR (blocks submission), WARNING (advisory)
- Validators exit with code 1 if any ERROR is found

## Regulatory context
- Deutsche Bundesbank reports to ECB under AnaCredit Regulation (ECB/2016/13)
- This is a highly regulated environment — advice must be conservative and accurate
- When uncertain, say so rather than guessing

## Tools available to you
You have access to `run_validation` and `check_record` tools (see tool definitions).
Use them when the user asks you to validate data or check specific records.
"""

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "run_validation",
        "description": (
            "Run the full AnaCredit counterparty validation suite on a CSV file. "
            "Returns the combined stdout/stderr from both validators. "
            "Use this when the user asks to validate a CSV file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "csv_path": {
                    "type": "string",
                    "description": "Path to the semicolon-delimited CSV file to validate.",
                },
                "no_warnings": {
                    "type": "boolean",
                    "description": "If true, suppress WARNING lines from output.",
                    "default": False,
                },
            },
            "required": ["csv_path"],
        },
    },
    {
        "name": "check_record",
        "description": (
            "Validate a single counterparty record provided as a JSON object. "
            "Writes a temporary CSV and runs the validators on it. "
            "Use this when the user provides field values and wants to check them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "record": {
                    "type": "object",
                    "description": "Counterparty fields as key-value pairs.",
                }
            },
            "required": ["record"],
        },
    },
    {
        "name": "list_codelists",
        "description": "Return the available codelist names and their entry counts.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_codelist",
        "description": "Return all valid values for a named codelist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Codelist name, e.g. 'country_codes', 'institutional_sectors', "
                        "'legal_proceeding_status', 'enterprise_sizes', 'cp_id_types', "
                        "'accounting_standards', 'reporting_member_states'."
                    ),
                }
            },
            "required": ["name"],
        },
    },
]

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _run_validate_sh(csv_path: str, extra_args: list[str] | None = None) -> str:
    """Run validate.sh and return combined output."""
    validate_sh = WORKSPACE / "validate.sh"
    if not validate_sh.exists():
        return "ERROR: validate.sh not found in workspace root."
    cmd = ["bash", str(validate_sh), csv_path] + (extra_args or [])
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(WORKSPACE),
        )
        output = result.stdout
        if result.stderr:
            output += "\n[stderr]\n" + result.stderr
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return "ERROR: validation timed out after 60 seconds."
    except Exception as exc:
        return f"ERROR running validator: {exc}"


def tool_run_validation(csv_path: str, no_warnings: bool = False) -> str:
    path = Path(csv_path)
    if not path.is_absolute():
        path = WORKSPACE / csv_path
    if not path.exists():
        # Try data/ subdirectory
        alt = DATA_DIR / csv_path
        if alt.exists():
            path = alt
        else:
            return f"ERROR: file not found: {csv_path}"
    extra = ["--no-warnings"] if no_warnings else []
    return _run_validate_sh(str(path), extra)


def tool_check_record(record: dict) -> str:
    """Write record to a temp CSV and validate it."""
    import tempfile
    if not record:
        return "ERROR: empty record."
    # Build minimal CSV with the provided fields
    fieldnames = list(record.keys())
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False,
        encoding="utf-8-sig", newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerow(record)
        tmp_path = f.name
    try:
        return _run_validate_sh(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def tool_list_codelists() -> str:
    result = {}
    for f in sorted(CODELISTS.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            count = len(data) if isinstance(data, (list, dict)) else "?"
            result[f.stem] = count
        except Exception:
            result[f.stem] = "error reading"
    return json.dumps(result, indent=2)


def tool_get_codelist(name: str) -> str:
    path = CODELISTS / f"{name}.json"
    if not path.exists():
        return f"ERROR: codelist '{name}' not found. Use list_codelists to see available names."
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"ERROR reading codelist: {exc}"


def dispatch_tool(name: str, inputs: dict) -> str:
    if name == "run_validation":
        return tool_run_validation(inputs["csv_path"], inputs.get("no_warnings", False))
    if name == "check_record":
        return tool_check_record(inputs["record"])
    if name == "list_codelists":
        return tool_list_codelists()
    if name == "get_codelist":
        return tool_get_codelist(inputs["name"])
    return f"ERROR: unknown tool '{name}'"

# ---------------------------------------------------------------------------
# Console loop
# ---------------------------------------------------------------------------

WHO_AM_I = """\
=== AnaCredit Claude Console ===
User    : Per Nielsen (per.nielsen1@outlook.com)
Role    : Senior Architect — banking/regulatory reporting (Deutsche Bundesbank)
Project : AnaCredit ECB credit register validator
Model   : claude-sonnet-4-6
Tools   : run_validation, check_record, list_codelists, get_codelist
Docs    : /workspace/docs/  (mount PDFs and Excel codelist here)
Data    : /workspace/data/  (place CSV files here)
================================
Type your question, or:
  /validate <file>   run full validation on a CSV
  /quit              exit
"""


def run_console(initial_message: str | None = None) -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable is not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    history: list[dict] = []

    print(WHO_AM_I)

    if initial_message:
        print(f"[auto] {initial_message}")
        history.append({"role": "user", "content": initial_message})
        _send_and_reply(client, history)

    while True:
        try:
            user_input = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not user_input:
            continue
        if user_input in ("/quit", "/exit", "exit", "quit"):
            print("Exiting.")
            break
        if user_input.startswith("/validate "):
            csv_file = user_input[len("/validate "):].strip()
            user_input = f"Please validate the file: {csv_file}"

        history.append({"role": "user", "content": user_input})
        _send_and_reply(client, history)


def _send_and_reply(client: "anthropic.Anthropic", history: list[dict]) -> None:
    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=history,
        )

        # Collect text and tool_use blocks
        assistant_content = []
        text_parts: list[str] = []
        tool_calls: list[dict] = []

        for block in response.content:
            assistant_content.append(block)
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(block)

        if text_parts:
            print(f"\nClaude> {''.join(text_parts)}\n")

        # Append assistant turn to history
        history.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn" or not tool_calls:
            break

        # Execute tools and feed results back
        tool_results = []
        for tc in tool_calls:
            print(f"[tool: {tc.name}({json.dumps(tc.input)})]")
            result = dispatch_tool(tc.name, tc.input)
            print(f"[result preview: {result[:200]}{'...' if len(result) > 200 else ''}]")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": result,
            })

        history.append({"role": "user", "content": tool_results})

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="AnaCredit Claude Console")
    parser.add_argument("--who-am-i", action="store_true",
                        help="Print context summary and exit")
    parser.add_argument("--validate", metavar="CSV",
                        help="Run validation on a CSV file, then enter chat")
    args = parser.parse_args()

    if args.who_am_i:
        print(WHO_AM_I)
        return

    initial = None
    if args.validate:
        initial = f"Please validate the file: {args.validate}"

    run_console(initial_message=initial)


if __name__ == "__main__":
    main()

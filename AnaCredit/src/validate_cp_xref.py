"""
validate_cp_xref.py

AnaCredit Counterparty Cross-Reference Validator
=================================================
Implements the Referential Integrity rules from section 4.1 of the
AnaCredit Validation Rules Handbook (v22, valid from 2026-08-01)
that relate to counterparty-to-counterparty references:

  RI0140_DE  Head office undertaking must exist as a counterparty
  RI0150_DE  Immediate parent undertaking must exist as a counterparty
  RI0160_DE  Ultimate parent undertaking must exist as a counterparty

All three rules share the same formal structure (from section 4.1):

  Trigger : [Counterparty reference.<X> identifier] <> {}
  Definition:
    ([Counterparty reference.<X> identifier],
     [Counterparty reference.<X> identifier type])
    EXISTS IN {
      ([Counterparty reference.Counterparty identifier],
       [Counterparty reference.Counterparty identifier type])
    }
    WHERE [Counterparty reference.<X> identifier] <> {}

  Exception (per description text): if the referenced entity is a protected
  person (identifier type = 'Protected'), no counterparty record is required.

Usage (library):
    import pandas as pd
    from validate_cp_xref import validate_xref

    cp_df = pd.read_csv('counterparties.csv', sep=';', encoding='utf-8-sig', dtype=str)
    findings = validate_xref(cp_df)
    for f in findings:
        print(f)

Usage (CLI):
    python3 validate_cp_xref.py counterparties.csv [--output results.csv] [--summary]

Input CSV conventions (same as validate_counterparty.py):
  - Separator  : semicolon (;)
  - Encoding   : utf-8-sig
  - Column names: AnaCredit verbose attribute names OR snake_case internal names
  - cp_df must contain ALL counterparties in the submission
"""

import argparse
import sys
from dataclasses import dataclass
from typing import List

import pandas as pd

# ---------------------------------------------------------------------------
# Column normalisation
# ---------------------------------------------------------------------------

_VERBOSE = {
    'Type of counterparty identifier':                    'cp_id_type',
    'Counterparty identifier':                            'cp_id',
    'Type of head office undertaking identifier':         'head_office_id_type',
    'Head office undertaking identifier':                 'head_office_id',
    'Type of immediate parent undertaking identifier':    'immediate_parent_id_type',
    'Immediate parent undertaking identifier':            'immediate_parent_id',
    'Type of ultimate parent undertaking identifier':     'ultimate_parent_id_type',
    'Ultimate parent undertaking identifier':             'ultimate_parent_id',
}

_SNAKE = {
    'type_of_counterparty_identifier':                    'cp_id_type',
    'counterparty_identifier':                            'cp_id',
    'type_of_head_office_undertaking_identifier':         'head_office_id_type',
    'head_office_undertaking_identifier':                 'head_office_id',
    'type_of_immediate_parent_undertaking_identifier':    'immediate_parent_id_type',
    'immediate_parent_undertaking_identifier':            'immediate_parent_id',
    'type_of_ultimate_parent_undertaking_identifier':     'ultimate_parent_id_type',
    'ultimate_parent_undertaking_identifier':             'ultimate_parent_id',
}


def _normalise(col: str) -> str:
    if col in _VERBOSE:
        return _VERBOSE[col]
    key = (col.strip().lower()
             .replace(' ', '_').replace(':', '').replace('/', '_')
             .replace('-', '_').replace('(', '').replace(')', '').replace('.', ''))
    return _SNAKE.get(key, key)


def _normalise_df(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(columns={c: _normalise(c) for c in df.columns})


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    rule:        str
    severity:    str   # 'ERROR'
    cp_id:       str
    cp_id_type:  str
    field:       str
    ref_id:      str
    ref_id_type: str
    detail:      str

    def __str__(self) -> str:
        return (
            f"[{self.severity}] {self.rule} | "
            f"CP ({self.cp_id_type}:{self.cp_id}) | "
            f"{self.field} → ({self.ref_id_type}:{self.ref_id}) | "
            f"{self.detail}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOT_APPL = {'NOT_APPL', 'Non-applicable', 'non-applicable', 'NA', 'N/A'}


def _v(row: pd.Series, col: str) -> str:
    val = row.get(col, '')
    return '' if (val is None or (isinstance(val, float) and pd.isna(val))) else str(val).strip()


def _present(v: str) -> bool:
    return bool(v) and v not in _NOT_APPL


def _protected(id_type: str) -> bool:
    return id_type.lower() == 'protected'


# ---------------------------------------------------------------------------
# The three RI rules — identical structure, different field names
# ---------------------------------------------------------------------------

_RULES = [
    (
        'RI0140_DE',
        'head_office_id',
        'head_office_id_type',
        'Head office undertaking',
    ),
    (
        'RI0150_DE',
        'immediate_parent_id',
        'immediate_parent_id_type',
        'Immediate parent undertaking',
    ),
    (
        'RI0160_DE',
        'ultimate_parent_id',
        'ultimate_parent_id_type',
        'Ultimate parent undertaking',
    ),
]


# ---------------------------------------------------------------------------
# Main validation function
# ---------------------------------------------------------------------------

def validate_xref(cp_df: pd.DataFrame) -> List[Finding]:
    """
    Validate counterparty-to-counterparty referential integrity.

    Parameters
    ----------
    cp_df : pd.DataFrame
        All counterparties in the submission.  Column names may be either
        AnaCredit verbose attribute names or snake_case internal names.
        Must include at minimum: counterparty_identifier and
        type_of_counterparty_identifier (or their verbose equivalents),
        plus the six hierarchy columns for any rules to fire.

    Returns
    -------
    List[Finding]
        One Finding per violation, sorted by rule then counterparty ID.
    """
    df = _normalise_df(cp_df.fillna(''))

    for col in ('cp_id', 'cp_id_type'):
        if col not in df.columns:
            raise ValueError(
                f"cp_df is missing required column '{col}'. "
                f"Provide 'counterparty_identifier' / 'type_of_counterparty_identifier'."
            )

    # Build the set of all known (cp_id, cp_id_type) pairs in this submission
    known: set[tuple[str, str]] = set(
        zip(df['cp_id'].str.strip(), df['cp_id_type'].str.strip())
    )

    findings: List[Finding] = []

    for _, row in df.iterrows():
        cp_id      = _v(row, 'cp_id')
        cp_id_type = _v(row, 'cp_id_type')

        for rule_code, id_col, type_col, label in _RULES:
            ref_id      = _v(row, id_col)
            ref_id_type = _v(row, type_col)

            # Rule only fires when the reference identifier is present
            if not _present(ref_id):
                continue

            # Per rule description: protected persons are exempt —
            # no counterparty record is required for them
            if _protected(ref_id_type):
                continue

            if (ref_id, ref_id_type) not in known:
                findings.append(Finding(
                    rule=rule_code,
                    severity='ERROR',
                    cp_id=cp_id,
                    cp_id_type=cp_id_type,
                    field=id_col,
                    ref_id=ref_id,
                    ref_id_type=ref_id_type,
                    detail=(
                        f"{label} ({ref_id_type}:{ref_id}) is referenced "
                        f"but does not exist as a counterparty in cp_df."
                    ),
                ))

    findings.sort(key=lambda f: (f.rule, f.cp_id))
    return findings


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _print_report(findings: List[Finding], cp_count: int) -> None:
    errors = [f for f in findings if f.severity == 'ERROR']

    print()
    print('=' * 72)
    print('  AnaCredit Counterparty Cross-Reference Validation')
    print('  Rules: RI0140_DE · RI0150_DE · RI0160_DE  (section 4.1, v22)')
    print(f'  Counterparties : {cp_count}')
    print(f'  Errors         : {len(errors)}')
    print('=' * 72)

    if errors:
        print(f'\n  --- ERRORS ({len(errors)}) ---\n')
        for f in errors:
            print(f'  CP       : ({f.cp_id_type}:{f.cp_id})')
            print(f'  Rule     : {f.rule}')
            print(f'  Field    : {f.field}')
            print(f'  Missing  : ({f.ref_id_type}:{f.ref_id})')
            print(f'  Detail   : {f.detail}')
            print()
    else:
        print('\n  No cross-reference violations found.\n')

    print('=' * 72)
    print()


def _save_csv(findings: List[Finding], path: str) -> None:
    rows = [
        {
            'severity':    f.severity,
            'rule':        f.rule,
            'cp_id':       f.cp_id,
            'cp_id_type':  f.cp_id_type,
            'field':       f.field,
            'ref_id':      f.ref_id,
            'ref_id_type': f.ref_id_type,
            'detail':      f.detail,
        }
        for f in findings
    ]
    pd.DataFrame(rows).to_csv(path, sep=';', index=False, encoding='utf-8-sig')
    print(f'Report written to {path}')


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            'AnaCredit counterparty cross-reference validator '
            '(RI0140_DE / RI0150_DE / RI0160_DE)'
        )
    )
    parser.add_argument(
        'input_csv',
        help='Counterparty CSV containing all counterparties (semicolon-delimited, utf-8-sig)',
    )
    parser.add_argument('--output',  help='Write findings to this CSV file')
    parser.add_argument('--summary', action='store_true', help='Summary line only')
    args = parser.parse_args()

    cp_df = pd.read_csv(args.input_csv, sep=';', encoding='utf-8-sig', dtype=str)

    findings = validate_xref(cp_df)

    if args.summary:
        errors = sum(1 for f in findings if f.severity == 'ERROR')
        print(f'Records: {len(cp_df)} | Errors: {errors}')
    else:
        _print_report(findings, len(cp_df))

    if args.output:
        _save_csv(findings, args.output)

    sys.exit(1 if any(f.severity == 'ERROR' for f in findings) else 0)


if __name__ == '__main__':
    main()

"""
postal_code_validator.py

AnaCredit Postal Code Format Validator
=======================================
Implements section 4.5 of the AnaCredit Validation Rules Handbook
(Handbuch zu den AnaCredit-Validierungsregeln, v22, gültig ab 01.08.2026):
"Prüfung auf Postleitzahlenformate"

130 country-specific regex rules sourced from the Bundesbank handbook,
loaded from codelists/postal_code_formats.json at instantiation.

Countries not present in the JSON have no format constraint beyond presence —
the general data type spec applies (per section 4.5 introductory text).

Usage:
    from postal_code_validator import PostalCodeValidator

    pv = PostalCodeValidator('/path/to/codelists/postal_code_formats.json')

    result = pv.validate('12345', 'DE')
    if not result.valid:
        print(result.rule, result.message)

    # Bulk check across a DataFrame column:
    results = pv.validate_series(df['postal_code'], df['country'])
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class PostalCodeResult:
    valid:   bool
    rule:    Optional[str]   # PSTL_CD_DS_xxx  — None if country has no rule
    message: Optional[str]  # human-readable detail — None if valid or no rule


class PostalCodeValidator:
    """
    Validates postal codes against country-specific format rules
    from AnaCredit section 4.5.

    Parameters
    ----------
    formats_path : str | Path
        Path to postal_code_formats.json (codelists directory).
    """

    def __init__(self, formats_path: str | Path):
        with open(formats_path, encoding='utf-8') as f:
            raw = json.load(f)

        self._rules: dict[str, dict] = {}
        errors = []
        for iso, entry in raw.items():
            try:
                compiled = re.compile(entry['pattern'])
                self._rules[iso] = {
                    'rule':     entry['rule'],
                    'pattern':  entry['pattern'],
                    'compiled': compiled,
                }
            except re.error as exc:
                errors.append(f"  {iso}: {exc}")

        if errors:
            raise ValueError(
                f"postal_code_formats.json contains invalid patterns:\n"
                + '\n'.join(errors)
            )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def has_rule(self, country_iso: str) -> bool:
        """True if a format rule exists for this country."""
        return country_iso.upper() in self._rules

    def validate(self, postal_code: str, country_iso: str) -> PostalCodeResult:
        """
        Validate a single postal code against the rule for country_iso.

        Returns PostalCodeResult with:
          valid=True, rule=None, message=None   — if country has no rule
          valid=True, rule=<code>, message=None — format matches
          valid=False, rule=<code>, message=<detail> — format mismatch
        """
        iso = country_iso.strip().upper()
        pc  = postal_code.strip()

        if iso not in self._rules:
            return PostalCodeResult(valid=True, rule=None, message=None)

        entry = self._rules[iso]
        rule  = entry['rule']

        if re.fullmatch(entry['compiled'], pc):
            return PostalCodeResult(valid=True, rule=rule, message=None)

        return PostalCodeResult(
            valid=False,
            rule=rule,
            message=(
                f'Postal code "{pc}" does not match the required format '
                f'for {iso} (rule {rule}). '
                f'Expected pattern: {entry["pattern"]}'
            ),
        )

    def validate_series(self, postal_codes, country_codes) -> list[PostalCodeResult]:
        """
        Validate two parallel iterables (e.g. DataFrame columns).
        Returns a list of PostalCodeResult in the same order.
        """
        return [
            self.validate(str(pc), str(cc))
            for pc, cc in zip(postal_codes, country_codes)
        ]

    @property
    def covered_countries(self) -> set[str]:
        """Set of ISO codes for which a format rule is defined."""
        return set(self._rules)


# ---------------------------------------------------------------------------
# Convenience factory — resolves path relative to this file's codelists dir
# ---------------------------------------------------------------------------

def default_validator() -> PostalCodeValidator:
    """
    Return a PostalCodeValidator loaded from the standard codelists location
    (../codelists/postal_code_formats.json relative to this file).
    """
    path = Path(__file__).parent.parent / 'codelists' / 'postal_code_formats.json'
    return PostalCodeValidator(path)


# ---------------------------------------------------------------------------
# CLI — standalone usage for quick spot-checks
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import sys

    if len(sys.argv) < 3:
        print('Usage: python3 postal_code_validator.py <ISO> <postal_code>')
        print('Example: python3 postal_code_validator.py DE 12345')
        sys.exit(1)

    iso_arg = sys.argv[1].upper()
    pc_arg  = sys.argv[2]

    pv     = default_validator()
    result = pv.validate(pc_arg, iso_arg)

    if result.rule is None:
        print(f'[INFO] No format rule defined for {iso_arg} — no check applied.')
        sys.exit(0)
    elif result.valid:
        print(f'[OK]   {iso_arg} "{pc_arg}" matches rule {result.rule}')
        sys.exit(0)
    else:
        print(f'[FAIL] {result.message}')
        sys.exit(1)

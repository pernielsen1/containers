"""AnaCredit postal code formats (Bundesbank validation handbook v22,
section 4.5) as a class, plus module-level wrappers exposed to run_sql.py
as UDFs (see udf_definitions.csv):

    anacredit_postal_valid(postal_code, country)     -> 1 / 0
    anacredit_postal_verbosed(postal_code, country)  -> corrected code or NULL

Rules live in postal_code_formats.csv (country;rule;pattern, semicolon,
utf-8-sig), one regex per country, next to this file. A country with no
row has no format constraint, so any code is valid for it.

verbosed() repairs "noise": it drops everything but letters and digits,
then tries to put back at most one separator (blank or '-') so the
result fully matches the country's regex -- Sweden '12345' -> '123 45',
Poland '12345' -> '12-345', Germany '123 45' -> '12345'. NULL if no
such form exists.
"""
import csv
import re
from pathlib import Path

DEFAULT_FORMATS_CSV = Path(__file__).resolve().parent / "postal_code_formats.csv"
SEPARATORS = (" ", "-")


class AnaCredit_PostalCode:
    def __init__(self, formats_csv=DEFAULT_FORMATS_CSV):
        self._rules = {}
        with open(Path(formats_csv).expanduser(), encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f, delimiter=";"):
                self._rules[row["country"].strip().upper()] = (row["rule"], re.compile(row["pattern"]))

    def _rule_for(self, country):
        return self._rules.get(country.strip().upper())

    def validate(self, postal_code, country):
        """True if postal_code matches the country's format (or the country
        has no format); NULL in, NULL out."""
        if postal_code is None or country is None:
            return None
        rule = self._rule_for(country)
        return True if rule is None else rule[1].fullmatch(postal_code) is not None

    def verbosed(self, postal_code, country):
        """The postal code with noise removed and the country's separator
        restored, or None if it cannot be made to match."""
        if postal_code is None or country is None:
            return None
        rule = self._rule_for(country)
        code = postal_code.strip()
        if rule is None or rule[1].fullmatch(code):
            return code
        core = re.sub(r"[^0-9A-Za-z]", "", code).upper()
        candidates = [core] + [core[:i] + sep + core[i:]
                               for i in range(1, len(core)) for sep in SEPARATORS]
        return next((c for c in candidates if rule[1].fullmatch(c)), None)


_default = None


def _instance():
    global _default
    if _default is None:
        _default = AnaCredit_PostalCode()
    return _default


def postal_valid(postal_code, country):
    return _instance().validate(postal_code, country)


def postal_verbosed(postal_code, country):
    return _instance().verbosed(postal_code, country)

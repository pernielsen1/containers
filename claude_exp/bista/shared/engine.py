"""
shared/engine.py — Calculation engine, shared by BISTA and KreStA.

Derives calculated fields from input data using the catalogue's formula rules.
Data format throughout: {(cat_form, field_id): value_eur_int}
"""

import re


class CalculationEngine:
    def __init__(self, catalogue):
        self.catalogue = catalogue

    def apply(self, data):
        """
        Returns (merged, computed) where:
          merged   = user data + all derivable calculated values
                     (user-supplied values take precedence over computed ones)
          computed = dict of values the engine derived independently from inputs,
                     regardless of what the user supplied for those fields
        Iterates up to 5 passes to resolve dependency chains.
        """
        result   = dict(data)
        computed = {}

        for _ in range(5):
            changed = False
            for (cat_form, field_id), formula in self.catalogue.calcs.items():
                val = self._eval(cat_form, field_id, formula, result)
                if val is None:
                    continue
                computed[(cat_form, field_id)] = val
                if (cat_form, field_id) not in result:
                    result[(cat_form, field_id)] = val
                    changed = True
            if not changed:
                break
        return result, computed

    def check_conflicts(self, user_data, computed):
        """
        Warn when a user-supplied field marked 'calculate' in the catalogue
        differs from the independently computed value by more than €500.
        Returns list of warning strings.
        """
        warnings = []
        for (cat_form, fid), user_val in user_data.items():
            if self.catalogue.fields.get((cat_form, fid)) != "calculate":
                continue
            engine_val = computed.get((cat_form, fid))
            if engine_val is None:
                continue
            if abs(user_val - engine_val) > 500:
                warnings.append(
                    f"  {cat_form}/{fid}: you supplied {user_val:,} "
                    f"but engine computed {engine_val:,} — check inputs"
                )
        return warnings

    def _eval(self, cat_form, target_fid, formula, data):
        """
        Parse and evaluate a formula string. Tokens are field_ids in the same
        form. If a bare row token (e.g. '210') is used in a formula for a
        target that has a column suffix (e.g. '260/03'), the column is inherited
        automatically.
        """
        col_suffix = None
        if "/" in target_fid:
            col_suffix = target_fid.split("/")[1]

        tokens = re.findall(r'[+\-]|[^\s+\-]+', formula.replace(" ", ""))
        sign = 1
        total = 0
        any_found = False

        for token in tokens:
            if token == "+":
                sign = 1
            elif token == "-":
                sign = -1
            else:
                fid = token
                if col_suffix and "/" not in fid:
                    fid_with_col = f"{fid}/{col_suffix}"
                    val = data.get((cat_form, fid_with_col), data.get((cat_form, fid)))
                else:
                    val = data.get((cat_form, fid))

                if val is not None:
                    total += sign * val
                    any_found = True
                sign = 1

        return total if any_found else None

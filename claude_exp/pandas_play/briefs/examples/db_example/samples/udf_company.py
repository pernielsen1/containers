"""Example wrapper (Part 3): expose a class living elsewhere in the tree as a UDF.

company_identifiers.py sits in ~/containers/snippets -- udf_extra.csv puts
that directory on sys.path through its `path` column. The instance is built
once and reused for every row.
"""
from company_identifiers import company_identifiers

_ci = company_identifiers()


def validate_company_id(s, country_code):
    """Return the validator's result dict (run_sql_udf stores it as JSON text)."""
    if s is None or country_code is None:
        return None
    return _ci.validate_COMPANY_ID(s, country_code)

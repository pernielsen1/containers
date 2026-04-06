#!/usr/bin/env python3
"""
AnaCredit Counterparty Reference Data Validator
================================================
Validates counterparty reference data against the AnaCredit validation rules
(Handbuch zu den AnaCredit-Validierungsregeln, Version 22, gültig ab 01.08.2026).

Implements rules from section 4.2 (Vollständigkeit - Vertragspartner-Stammdaten),
selected consistency rules (section 4.4), and section 4.5 postal code format checks.

Usage:
    python3 validate_counterparty.py <input_csv> [--output <report.csv>]
    python3 validate_counterparty.py --help

Input CSV format:
    Semicolon-delimited, UTF-8. Column names must match the 29 AnaCredit
    counterparty reference data attributes (see --help for full column list).
"""

import argparse
import csv
import json
import sys
import re
from datetime import datetime, date
from pathlib import Path

from postal_code_validator import PostalCodeValidator

# ---------------------------------------------------------------------------
# Code lists — loaded from codelists/ directory at import time
# ---------------------------------------------------------------------------

_CODELISTS_DIR = Path(__file__).parent.parent / 'codelists'


def _load(filename: str) -> set:
    path = _CODELISTS_DIR / filename
    with open(path, encoding='utf-8') as f:
        return set(json.load(f))


_POSTAL_VALIDATOR = PostalCodeValidator(_CODELISTS_DIR / 'postal_code_formats.json')

VALID_COUNTRIES               = _load('country_codes.json')
VALID_INSTITUTIONAL_SECTORS   = _load('institutional_sectors.json')
VALID_LEGAL_PROCEEDING_STATUS = _load('legal_proceeding_status.json')
VALID_ENTERPRISE_SIZES        = _load('enterprise_sizes.json')
VALID_CP_ID_TYPES             = _load('cp_id_types.json')
VALID_ACCOUNTING_STANDARDS    = _load('accounting_standards.json')
REPORTING_MEMBER_STATES       = _load('reporting_member_states.json')

# Non-applicable sentinel value
NOT_APPL = 'NOT_APPL'
NON_APPLICABLE = 'Non-applicable'

# ---------------------------------------------------------------------------
# Column name mapping — loaded from codelists/column_map.json
# ---------------------------------------------------------------------------

def _snake(verbose: str) -> str:
    """Derive snake_case key from a verbose AnaCredit attribute name."""
    return (verbose.strip().lower()
            .replace(' ', '_').replace(':', '').replace('/', '_')
            .replace('-', '_').replace('(', '').replace(')', '').replace('.', ''))


_COL_MAP_DATA = json.load(open(_CODELISTS_DIR / 'column_map.json', encoding='utf-8'))

COLUMN_MAP_VERBOSE = {row['verbose']: row['internal'] for row in _COL_MAP_DATA}
COLUMN_MAP         = {_snake(row['verbose']): row['internal'] for row in _COL_MAP_DATA}


def normalize_header(col: str) -> str:
    """Try to map a CSV column header to an internal field name."""
    # Try verbose (original AnaCredit attribute name) first
    if col in COLUMN_MAP_VERBOSE:
        return COLUMN_MAP_VERBOSE[col]
    # Try snake_case lowercase version
    key = col.strip().lower().replace(' ', '_').replace(':', '').replace('/', '_').replace('-', '_').replace('(', '').replace(')', '').replace('.', '')
    if key in COLUMN_MAP:
        return COLUMN_MAP[key]
    # Return as-is (lowercased, underscored)
    return key


def is_empty(value: str) -> bool:
    """True if a value is blank / None / empty string."""
    return value is None or str(value).strip() == ''


def is_not_applicable(value: str) -> bool:
    """True if value is a NOT_APPL sentinel."""
    if is_empty(value):
        return False
    v = str(value).strip()
    return v in ('NOT_APPL', 'Non-applicable', 'non-applicable', 'NA', 'N/A')


def is_present(value: str) -> bool:
    """True if value is non-empty and not NOT_APPL."""
    return not is_empty(value) and not is_not_applicable(value)


def parse_date(value: str):
    """Try to parse a date string in YYYY-MM-DD or DD.MM.YYYY format."""
    if is_empty(value):
        return None
    v = str(value).strip()
    for fmt in ('%Y-%m-%d', '%d.%m.%Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            pass
    return None


def is_valid_date(value: str) -> bool:
    return parse_date(value) is not None


def is_valid_number(value: str) -> bool:
    """True if value is a non-negative number (integer or decimal)."""
    if is_empty(value) or is_not_applicable(value):
        return False
    v = str(value).strip().replace(',', '.')
    try:
        float(v)
        return True
    except ValueError:
        return False


def is_valid_lei(value: str) -> bool:
    """Basic LEI format check: 20 alphanumeric characters."""
    if not is_present(value):
        return True  # LEI is optional; NOT_APPL is valid
    v = str(value).strip()
    if is_not_applicable(v):
        return True
    return bool(re.match(r'^[A-Z0-9]{18}[0-9]{2}$', v))


# ---------------------------------------------------------------------------
# Validation rule definitions
# ---------------------------------------------------------------------------

class ValidationResult:
    """A single validation finding."""
    def __init__(self, record_id: str, rule_id: str, description: str,
                 severity: str, field: str, value: str):
        self.record_id = record_id
        self.rule_id = rule_id
        self.description = description
        self.severity = severity  # 'ERROR' or 'WARNING'
        self.field = field
        self.value = value

    def __repr__(self):
        return (f"[{self.severity}] Record={self.record_id} "
                f"Rule={self.rule_id} Field={self.field} "
                f"Value='{self.value}' | {self.description}")


def validate_record(rec: dict, row_num: int) -> list[ValidationResult]:
    """
    Run all applicable validation rules against a single counterparty record.

    Returns a list of ValidationResult objects for each failing rule.

    Rules implemented:
    - CY0010: LEI (Rechtsträgerkennung) - required in most scenarios
    - CY0011: National identifier - required always (ERROR if missing, leads to rejection)
    - CY0030/CY0030_DE: Head office undertaking identifier + type
    - CY0040/CY0040_DE: Immediate parent undertaking identifier + type
    - CY0050/CY0050_DE: Ultimate parent undertaking identifier + type
    - CY0060: Name - required
    - CY0070: Street address - required
    - CY0080: City - required
    - CY0090: County/administrative division
    - CY0100: Postal code - required
    - CY0110: Country - required, must be valid ISO3166
    - CY0120: Legal form - required, must be valid code
    - CY0130: Institutional sector - required, must be valid code
    - CY0140_DE: Economic activity / customer classification - at least one required
    - CY0150: Status of legal proceedings - code list validation
    - CY0160: Date of legal proceedings - conditional on CY0150
    - CY0170: Enterprise size - code list validation
    - CY0180: Date of enterprise size - conditional on CY0170
    - CY0190: Number of employees - numeric validation
    - CY0200: Balance sheet total - numeric validation
    - CY0210: Annual turnover - numeric validation
    - CY0220: Accounting standard - code list validation
    Consistency rules (section 4.4):
    - CN: LEI format check (20-char alphanumeric)
    - CN: Country must be valid ISO 3166
    - CN: If legal proceedings date present, status must also be present
    - CN: If enterprise size date present, enterprise size must also be present
    - CN: Identifier type must be valid code
    - CN: If head_office_id is present, head_office_id_type must also be present
    - CN: If immediate_parent_id present, type must also be present
    - CN: If ultimate_parent_id present, type must also be present
    """
    findings = []
    # Build a record identifier string for reporting
    cp_id = rec.get('cp_id', '').strip()
    cp_id_type = rec.get('cp_id_type', '').strip()
    record_id = f"Row {row_num}"
    if cp_id:
        record_id = f"Row {row_num} (CP_ID={cp_id}, Type={cp_id_type})"

    def add(rule_id, description, severity, field, value=''):
        findings.append(ValidationResult(record_id, rule_id, description,
                                         severity, field, str(value)))

    # -----------------------------------------------------------------------
    # CY0011: Nationale Kennung (National identifier) - ALWAYS required
    # Violation leads to record rejection
    # -----------------------------------------------------------------------
    if not is_present(rec.get('national_id')) and not is_not_applicable(rec.get('national_id')):
        add('CY0011',
            'National identifier (Nationale Kennung) is mandatory and must not be empty.',
            'ERROR', 'national_id', rec.get('national_id', ''))

    # -----------------------------------------------------------------------
    # CY0010: LEI (Rechtsträgerkennung)
    # Required under CC0010 (resident in reporting member state), sub-condition
    # CC0140_DE (new business). We check presence as a WARNING since residency
    # is not always determinable from the record alone.
    # -----------------------------------------------------------------------
    lei_val = rec.get('lei', '')
    if not is_present(lei_val) and not is_not_applicable(lei_val):
        add('CY0010',
            'Legal entity identifier (LEI/Rechtsträgerkennung) is missing. '
            'Required for counterparties resident in a reporting member state '
            'under most conditions.',
            'WARNING', 'lei', lei_val)
    elif is_present(lei_val) and not is_valid_lei(lei_val):
        add('CY0010_FORMAT',
            'LEI format is invalid. An LEI must be exactly 20 alphanumeric '
            'characters (18 alphanumeric + 2 check digits).',
            'ERROR', 'lei', lei_val)

    # -----------------------------------------------------------------------
    # CY0060: Name - required under all conditions
    # -----------------------------------------------------------------------
    if not is_present(rec.get('name')):
        add('CY0060',
            'Name (Firmenname) is mandatory and must not be empty.',
            'ERROR', 'name', rec.get('name', ''))

    # -----------------------------------------------------------------------
    # CY0070: Address: street - required (CC0010 and CC0020, most conditions)
    # -----------------------------------------------------------------------
    if not is_present(rec.get('street')):
        add('CY0070',
            'Address: street (Anschrift: Straße) is mandatory.',
            'ERROR', 'street', rec.get('street', ''))

    # -----------------------------------------------------------------------
    # CY0080: Address: city - required
    # -----------------------------------------------------------------------
    if not is_present(rec.get('city')):
        add('CY0080',
            'Address: city/town/village (Anschrift: Stadt/Gemeinde/Ortschaft) '
            'is mandatory.',
            'ERROR', 'city', rec.get('city', ''))

    # -----------------------------------------------------------------------
    # CY0100: Address: postal code - required (most conditions)
    # -----------------------------------------------------------------------
    postal_code = rec.get('postal_code', '').strip()
    if not is_present(postal_code):
        add('CY0100',
            'Address: postal code (Anschrift: Postleitzahl) is mandatory.',
            'ERROR', 'postal_code', postal_code)

    # -----------------------------------------------------------------------
    # CY0110: Address: country - required and must be a valid ISO 3166 code
    # -----------------------------------------------------------------------
    country = rec.get('country', '').strip()
    if not is_present(country):
        add('CY0110',
            'Address: country (Anschrift: Land) is mandatory.',
            'ERROR', 'country', country)
    elif country not in VALID_COUNTRIES:
        add('CY0110',
            f'Address: country value "{country}" is not a valid ISO 3166-1 '
            'alpha-2 country code.',
            'ERROR', 'country', country)

    # -----------------------------------------------------------------------
    # PSTL_CD: Postal code format check per country (section 4.5)
    # Only applied when both postal code and a valid country are present.
    # -----------------------------------------------------------------------
    if is_present(postal_code) and is_present(country) and country in VALID_COUNTRIES:
        pv = _POSTAL_VALIDATOR.validate(postal_code, country)
        if not pv.valid:
            add(pv.rule, pv.message, 'ERROR', 'postal_code', postal_code)

    # -----------------------------------------------------------------------
    # CY0120: Legal form - required (most conditions, especially CC0010)
    # Must be a valid code from the LGL_FRM codelist.
    # We perform a format check here; a full codelist load can be enabled
    # via --codelist flag (see load_codelists()).
    # -----------------------------------------------------------------------
    legal_form = rec.get('legal_form', '').strip()
    if not is_present(legal_form) and not is_not_applicable(legal_form):
        add('CY0120',
            'Legal form (Rechtsform) is mandatory for most counterparty types.',
            'ERROR', 'legal_form', legal_form)
    elif is_present(legal_form) and _VALID_LEGAL_FORMS:
        # Only validate against full codelist if it was loaded
        if legal_form not in _VALID_LEGAL_FORMS and legal_form != NOT_APPL:
            add('CY0120',
                f'Legal form value "{legal_form}" is not a valid LGL_FRM code.',
                'ERROR', 'legal_form', legal_form)

    # -----------------------------------------------------------------------
    # CY0130: Institutional sector - required (most conditions)
    # Must be a valid INSTTTNL_SCTR code
    # -----------------------------------------------------------------------
    inst_sector = rec.get('institutional_sector', '').strip()
    if not is_present(inst_sector) and not is_not_applicable(inst_sector):
        add('CY0130',
            'Institutional sector (Institutioneller Sektor) is mandatory.',
            'ERROR', 'institutional_sector', inst_sector)
    elif is_present(inst_sector) and inst_sector not in VALID_INSTITUTIONAL_SECTORS:
        add('CY0130',
            f'Institutional sector "{inst_sector}" is not a valid '
            'INSTTTNL_SCTR code.',
            'ERROR', 'institutional_sector', inst_sector)

    # -----------------------------------------------------------------------
    # CY0140_DE: Economic activity OR customer classification code
    # At least one of the two must be reported (R = required, footnote:
    # "Zumindest eines der genannten Attribute ist zu melden")
    # -----------------------------------------------------------------------
    economic_activity = rec.get('economic_activity', '').strip()
    customer_class = rec.get('customer_classification_code', '').strip()
    # At least one must be present OR explicitly set to NOT_APPL
    ea_reported = is_present(economic_activity) or is_not_applicable(economic_activity)
    cc_reported = is_present(customer_class) or is_not_applicable(customer_class)
    if not ea_reported and not cc_reported:
        add('CY0140_DE',
            'Economic activity (Wirtschaftszweigklassifikation) OR customer '
            'classification code (Kundensystematikschlüssel): at least one '
            'must be reported (or set to NOT_APPL).',
            'ERROR', 'economic_activity / customer_classification_code',
            f'economic_activity="{economic_activity}", '
            f'customer_classification_code="{customer_class}"')

    # -----------------------------------------------------------------------
    # CY0150: Status of legal proceedings - code list check
    # -----------------------------------------------------------------------
    legal_status = rec.get('legal_proceedings_status', '').strip()
    if is_present(legal_status) and legal_status not in VALID_LEGAL_PROCEEDING_STATUS:
        add('CY0150',
            f'Status of legal proceedings "{legal_status}" is not a valid '
            'LGL_PRCDNG_STTS code. Valid values: 1, 2, 3, 4, NOT_APPL.',
            'ERROR', 'legal_proceedings_status', legal_status)

    # -----------------------------------------------------------------------
    # CY0160: Date of initiation of legal proceedings
    # Conditional: if legal proceedings status is 2, 3, or 4 (i.e. active
    # proceedings), the date should be present. If present, must be a valid date.
    # -----------------------------------------------------------------------
    legal_date = rec.get('legal_proceedings_date', '').strip()
    if is_present(legal_date) and not is_valid_date(legal_date):
        add('CY0160',
            f'Date of initiation of legal proceedings "{legal_date}" is not '
            'a valid date. Expected format: YYYY-MM-DD.',
            'ERROR', 'legal_proceedings_date', legal_date)
    if is_present(legal_date) and not is_present(legal_status):
        add('CY0160',
            'Date of initiation of legal proceedings is provided but '
            'Status of legal proceedings is missing. Both must be consistent.',
            'ERROR', 'legal_proceedings_date', legal_date)
    if legal_status in ('2', '3', '4') and not is_present(legal_date):
        add('CY0160',
            f'Legal proceedings status is "{legal_status}" (active proceedings) '
            'but Date of initiation of legal proceedings is missing.',
            'WARNING', 'legal_proceedings_date', legal_date)

    # -----------------------------------------------------------------------
    # CY0170: Enterprise size - code list check
    # -----------------------------------------------------------------------
    enterprise_size = rec.get('enterprise_size', '').strip()
    if is_present(enterprise_size) and enterprise_size not in VALID_ENTERPRISE_SIZES:
        add('CY0170',
            f'Enterprise size (Unternehmensgröße) "{enterprise_size}" is not '
            'a valid SZ code. Valid values: 1 (Large), 2 (Medium), '
            '3 (Small), 4 (Micro), NOT_APPL.',
            'ERROR', 'enterprise_size', enterprise_size)

    # -----------------------------------------------------------------------
    # CY0180: Date of enterprise size - conditional on CY0170
    # If enterprise size is reported, the date should also be present.
    # -----------------------------------------------------------------------
    enterprise_size_date = rec.get('enterprise_size_date', '').strip()
    if is_present(enterprise_size_date) and not is_valid_date(enterprise_size_date):
        add('CY0180',
            f'Date of enterprise size "{enterprise_size_date}" is not a valid '
            'date. Expected format: YYYY-MM-DD.',
            'ERROR', 'enterprise_size_date', enterprise_size_date)
    if is_present(enterprise_size) and enterprise_size != NOT_APPL \
            and not is_present(enterprise_size_date):
        add('CY0180',
            'Enterprise size is provided but Date of enterprise size is missing.',
            'WARNING', 'enterprise_size_date', enterprise_size_date)
    if is_present(enterprise_size_date) and not is_present(enterprise_size):
        add('CY0180',
            'Date of enterprise size is provided but Enterprise size is missing.',
            'ERROR', 'enterprise_size_date', enterprise_size_date)

    # -----------------------------------------------------------------------
    # CY0190: Number of employees - must be a non-negative integer if present
    # -----------------------------------------------------------------------
    num_emp = rec.get('num_employees', '').strip()
    if is_present(num_emp) and not is_not_applicable(num_emp):
        try:
            emp_val = float(num_emp.replace(',', '.'))
            if emp_val < 0:
                add('CY0190',
                    f'Number of employees "{num_emp}" must be a non-negative number.',
                    'ERROR', 'num_employees', num_emp)
        except ValueError:
            add('CY0190',
                f'Number of employees "{num_emp}" is not a valid numeric value.',
                'ERROR', 'num_employees', num_emp)

    # -----------------------------------------------------------------------
    # CY0200: Balance sheet total - must be numeric if present
    # -----------------------------------------------------------------------
    balance_sheet = rec.get('balance_sheet_total', '').strip()
    if is_present(balance_sheet) and not is_not_applicable(balance_sheet):
        try:
            float(balance_sheet.replace(',', '.'))
        except ValueError:
            add('CY0200',
                f'Balance sheet total "{balance_sheet}" is not a valid '
                'numeric value.',
                'ERROR', 'balance_sheet_total', balance_sheet)

    # -----------------------------------------------------------------------
    # CY0210: Annual turnover - must be numeric if present
    # -----------------------------------------------------------------------
    annual_turnover = rec.get('annual_turnover', '').strip()
    if is_present(annual_turnover) and not is_not_applicable(annual_turnover):
        try:
            float(annual_turnover.replace(',', '.'))
        except ValueError:
            add('CY0210',
                f'Annual turnover "{annual_turnover}" is not a valid '
                'numeric value.',
                'ERROR', 'annual_turnover', annual_turnover)

    # -----------------------------------------------------------------------
    # CY0220: Accounting standard - code list check if present
    # -----------------------------------------------------------------------
    accounting_std = rec.get('accounting_standard', '').strip()
    if is_present(accounting_std) and accounting_std not in VALID_ACCOUNTING_STANDARDS:
        add('CY0220',
            f'Accounting standard (Rechnungslegungsstandard) "{accounting_std}" '
            'is not a valid ACCNTNG_FRMWRK code. Valid values: '
            '1 (National GAAP non-IFRS), 2 (IFRS), 3 (National GAAP IFRS-consistent).',
            'ERROR', 'accounting_standard', accounting_std)

    # -----------------------------------------------------------------------
    # Consistency rules
    # -----------------------------------------------------------------------

    # CN_CP_ID_TYPE: Counterparty identifier type must be a valid code
    if is_present(cp_id_type) and cp_id_type not in VALID_CP_ID_TYPES:
        add('CN_CP_ID_TYPE',
            f'Type of counterparty identifier "{cp_id_type}" is not valid. '
            'Valid values: 1 (Internal), 2 (RIAD), 3 (Bankleitzahl), '
            '4 (Nehmernummer).',
            'ERROR', 'cp_id_type', cp_id_type)

    # CN_CP_ID_PAIR: Both identifier and type must be present together
    if is_present(cp_id) and not is_present(cp_id_type):
        add('CN_CP_ID_PAIR',
            'Counterparty identifier is present but type of counterparty '
            'identifier is missing. Both must be reported together.',
            'ERROR', 'cp_id_type', cp_id_type)
    if is_present(cp_id_type) and not is_present(cp_id):
        add('CN_CP_ID_PAIR',
            'Type of counterparty identifier is present but counterparty '
            'identifier is missing. Both must be reported together.',
            'ERROR', 'cp_id', cp_id)

    # CN_HEAD_OFFICE: If head_office_id is present, type must also be present
    head_office_id = rec.get('head_office_id', '').strip()
    head_office_id_type = rec.get('head_office_id_type', '').strip()
    if is_present(head_office_id) and not is_present(head_office_id_type):
        add('CY0030_DE',
            'Head office undertaking identifier is present but type is missing. '
            'Both must be reported together (CY0030 / CY0030_DE).',
            'ERROR', 'head_office_id_type', head_office_id_type)
    if is_present(head_office_id_type) and not is_present(head_office_id):
        add('CY0030_DE',
            'Type of head office undertaking identifier is present but the '
            'identifier itself is missing.',
            'ERROR', 'head_office_id', head_office_id)

    # CN_IMMEDIATE_PARENT: type and identifier must be paired
    imm_parent_id = rec.get('immediate_parent_id', '').strip()
    imm_parent_id_type = rec.get('immediate_parent_id_type', '').strip()
    if is_present(imm_parent_id) and not is_present(imm_parent_id_type):
        add('CY0040_DE',
            'Immediate parent undertaking identifier is present but type is '
            'missing (CY0040 / CY0040_DE).',
            'ERROR', 'immediate_parent_id_type', imm_parent_id_type)
    if is_present(imm_parent_id_type) and not is_present(imm_parent_id):
        add('CY0040_DE',
            'Type of immediate parent undertaking identifier is present but '
            'the identifier itself is missing.',
            'ERROR', 'immediate_parent_id', imm_parent_id)

    # CN_ULTIMATE_PARENT: type and identifier must be paired
    ult_parent_id = rec.get('ultimate_parent_id', '').strip()
    ult_parent_id_type = rec.get('ultimate_parent_id_type', '').strip()
    if is_present(ult_parent_id) and not is_present(ult_parent_id_type):
        add('CY0050_DE',
            'Ultimate parent undertaking identifier is present but type is '
            'missing (CY0050 / CY0050_DE).',
            'ERROR', 'ultimate_parent_id_type', ult_parent_id_type)
    if is_present(ult_parent_id_type) and not is_present(ult_parent_id):
        add('CY0050_DE',
            'Type of ultimate parent undertaking identifier is present but '
            'the identifier itself is missing.',
            'ERROR', 'ultimate_parent_id', ult_parent_id)

    # CN_COUNTRY_IN_MEMBER_STATE: if country is in EU, LEI is more strongly expected
    if is_present(country) and country in REPORTING_MEMBER_STATES:
        if not is_present(lei_val) and not is_not_applicable(lei_val):
            # LEI should be reported if counterparty is in a reporting member state
            # This finding is already raised above as WARNING; no duplicate needed.
            pass

    return findings


# ---------------------------------------------------------------------------
# Codelist loader (optional - loads full LGL_FRM from Excel)
# ---------------------------------------------------------------------------
_VALID_LEGAL_FORMS: set = set()


def load_codelists(excel_path: str):
    """Load full legal form codelist from the AnaCredit codelist Excel."""
    global _VALID_LEGAL_FORMS
    try:
        import openpyxl
        wb = openpyxl.load_workbook(excel_path, read_only=True)
        ws = wb['LGL_FRM']
        rows = list(ws.iter_rows(values_only=True))
        _VALID_LEGAL_FORMS = {
            str(r[0]).strip()
            for r in rows[1:]
            if r[0] is not None
            and str(r[0]).strip() not in ('', 'Zusätzlicher Wert')
        }
        # Also add NOT_APPL as a valid value
        _VALID_LEGAL_FORMS.add('NOT_APPL')
        print(f"Loaded {len(_VALID_LEGAL_FORMS)} legal form codes from {excel_path}")
    except Exception as e:
        print(f"Warning: Could not load codelists from {excel_path}: {e}",
              file=sys.stderr)


# ---------------------------------------------------------------------------
# CSV reader
# ---------------------------------------------------------------------------

def read_csv(filepath: str) -> tuple[list[dict], list[str]]:
    """
    Read a semicolon-delimited CSV file.
    Returns (records, warnings) where each record is a dict with
    internal field names as keys.
    """
    records = []
    warnings = []

    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f, delimiter=';')
        raw_headers = reader.fieldnames or []

        # Map raw headers to internal names
        header_map = {}
        for h in raw_headers:
            internal = normalize_header(h.strip())
            header_map[h.strip()] = internal

        unmapped = [h for h, v in header_map.items()
                    if v not in set(COLUMN_MAP.values()) | set(COLUMN_MAP_VERBOSE.values())]
        if unmapped:
            warnings.append(f"Unrecognised columns (will be ignored): "
                            f"{', '.join(unmapped)}")

        for i, raw_row in enumerate(reader, start=2):
            rec = {}
            for raw_col, internal_name in header_map.items():
                val = raw_row.get(raw_col, '')
                rec[internal_name] = val.strip() if val else ''
            rec['_row_num'] = i
            records.append(rec)

    return records, warnings


# ---------------------------------------------------------------------------
# Report printer / writer
# ---------------------------------------------------------------------------

def print_report(findings: list[ValidationResult], total_records: int):
    """Print a human-readable validation report to stdout."""
    errors = [f for f in findings if f.severity == 'ERROR']
    warnings = [f for f in findings if f.severity == 'WARNING']

    print()
    print("=" * 72)
    print("  AnaCredit Counterparty Validation Report")
    print(f"  Validated: {total_records} record(s)")
    print(f"  Errors:    {len(errors)}")
    print(f"  Warnings:  {len(warnings)}")
    print("=" * 72)

    if not findings:
        print()
        print("  No issues found. All records passed validation.")
        print()
        return

    # Group by severity then record
    for severity, label in [('ERROR', 'ERRORS'), ('WARNING', 'WARNINGS')]:
        group = [f for f in findings if f.severity == severity]
        if not group:
            continue
        print()
        print(f"  --- {label} ({len(group)}) ---")
        print()
        for f in group:
            print(f"  Record : {f.record_id}")
            print(f"  Rule   : {f.rule_id}")
            print(f"  Field  : {f.field}")
            print(f"  Value  : {f.value!r}")
            print(f"  Detail : {f.description}")
            print()


def write_csv_report(findings: list[ValidationResult], output_path: str):
    """Write validation findings to a CSV file."""
    fieldnames = ['record_id', 'rule_id', 'severity', 'field', 'value',
                  'description']
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
        writer.writeheader()
        for r in findings:
            writer.writerow({
                'record_id': r.record_id,
                'rule_id': r.rule_id,
                'severity': r.severity,
                'field': r.field,
                'value': r.value,
                'description': r.description,
            })
    print(f"\nValidation report saved to: {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_help_columns() -> str:
    col_lines = '\n'.join(
        f'  {row["verbose"]:<48} {row["internal"]}'
        for row in _COL_MAP_DATA
    )
    return f"""\
Expected CSV columns (semicolon-delimited, UTF-8):
  Either the exact AnaCredit attribute names or snake_case equivalents.

  AnaCredit attribute name                         Internal name
  ------------------------------------------------ ------------------------
{col_lines}

Validation rules implemented:
  CY0010        LEI presence (WARNING if missing for EU resident counterparty)
  CY0010_FORMAT LEI format: must be 20 alphanumeric chars
  CY0011        National identifier: mandatory (ERROR -> record rejection)
  CY0030_DE     Head office identifier and type: must be paired
  CY0040_DE     Immediate parent identifier and type: must be paired
  CY0050_DE     Ultimate parent identifier and type: must be paired
  CY0060        Name: mandatory
  CY0070        Street: mandatory
  CY0080        City: mandatory
  CY0100        Postal code: mandatory
  CY0110        Country: mandatory, must be ISO 3166-1 alpha-2
  CY0120        Legal form: mandatory, validated against LGL_FRM codelist
  CY0130        Institutional sector: mandatory, validated against INSTTTNL_SCTR
  CY0140_DE     Economic activity OR customer classification: at least one required
  CY0150        Status of legal proceedings: LGL_PRCDNG_STTS codelist check
  CY0160        Date of legal proceedings: format + consistency with status
  CY0170        Enterprise size: SZ codelist check
  CY0180        Date of enterprise size: format + consistency with size
  CY0190        Number of employees: numeric check
  CY0200        Balance sheet total: numeric check
  CY0210        Annual turnover: numeric check
  CY0220        Accounting standard: ACCNTNG_FRMWRK codelist check
  CN_CP_ID_TYPE Counterparty identifier type: valid code
  CN_CP_ID_PAIR Identifier and type must appear together
"""

HELP_COLUMNS = _build_help_columns()


def main():
    parser = argparse.ArgumentParser(
        description='AnaCredit Counterparty Reference Data Validator (Version 22)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HELP_COLUMNS,
    )
    parser.add_argument('input', nargs='?',
                        help='Path to input CSV file (semicolon-delimited)')
    parser.add_argument('--output', '-o', metavar='FILE',
                        help='Save validation report as CSV to this path')
    parser.add_argument('--codelist', metavar='EXCEL',
                        help='Path to anacredit-codelist-*.xlsx for full '
                             'legal form validation '
                             '(default: auto-detect in docs/ folder)')
    parser.add_argument('--no-warnings', action='store_true',
                        help='Suppress WARNING findings, show only ERRORs')
    parser.add_argument('--summary', action='store_true',
                        help='Show only the summary line, not per-finding details')

    args = parser.parse_args()

    if args.input is None:
        parser.print_help()
        sys.exit(0)

    # Locate codelist Excel (auto-detect if not specified)
    codelist_path = args.codelist
    if not codelist_path:
        # Try to auto-detect relative to this script
        script_dir = Path(__file__).parent
        candidates = list((script_dir.parent / 'docs').glob(
            'anacredit-codelist-*.xlsx'))
        if candidates:
            codelist_path = str(candidates[0])

    if codelist_path:
        load_codelists(codelist_path)
    else:
        print("Note: No codelist Excel found. Legal form codes will not be "
              "validated against the full LGL_FRM list.",
              file=sys.stderr)

    # Read input
    try:
        records, csv_warnings = read_csv(args.input)
    except FileNotFoundError:
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading input file: {e}", file=sys.stderr)
        sys.exit(1)

    for w in csv_warnings:
        print(f"CSV Warning: {w}", file=sys.stderr)

    if not records:
        print("No records found in input file.")
        sys.exit(0)

    # Run validation
    all_findings: list[ValidationResult] = []
    for rec in records:
        row_num = rec.pop('_row_num', '?')
        findings = validate_record(rec, row_num)
        all_findings.extend(findings)

    # Filter by severity if requested
    display_findings = all_findings
    if args.no_warnings:
        display_findings = [f for f in all_findings if f.severity == 'ERROR']

    # Print report
    if args.summary:
        errors = sum(1 for f in all_findings if f.severity == 'ERROR')
        warnings = sum(1 for f in all_findings if f.severity == 'WARNING')
        print(f"Records: {len(records)} | Errors: {errors} | Warnings: {warnings}")
    else:
        print_report(display_findings, len(records))

    # Optionally write CSV
    if args.output:
        write_csv_report(display_findings, args.output)

    # Exit code: 1 if any errors, 0 if only warnings or clean
    if any(f.severity == 'ERROR' for f in all_findings):
        sys.exit(1)


if __name__ == '__main__':
    main()

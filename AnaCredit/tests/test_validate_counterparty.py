"""Tests for AnaCredit counterparty validator — national identifier and legal form rules."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from validate_counterparty import validate_record

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def rule_ids(findings):
    return {f.rule_id for f in findings}

def errors(findings, rule_id):
    return [f for f in findings if f.rule_id == rule_id and f.severity == 'ERROR']

# Minimal valid DE counterparty — used as baseline for focused tests
_BASE = {
    'cp_id': 'TEST001', 'cp_id_type': '1',
    'lei': '529900HPSWCJB1WVVN19',
    'national_id': 'HRB1-A2016',
    'national_id_type': 'DE_TRD_RGSTR_CD',
    'other_id': '',
    'head_office_id': '', 'head_office_id_type': '',
    'immediate_parent_id': '', 'immediate_parent_id_type': '',
    'ultimate_parent_id': '', 'ultimate_parent_id_type': '',
    'name': 'Test GmbH', 'street': 'Teststr. 1',
    'city': 'Berlin', 'county': 'Berlin',
    'postal_code': '10115', 'country': 'DE',
    'legal_form': 'DE201',
    'institutional_sector': 'S11',
    'economic_activity': '64_19', 'customer_classification_code': '',
    'legal_proceedings_status': '1', 'legal_proceedings_date': '',
    'enterprise_size': 'NOT_APPL', 'enterprise_size_date': '',
    'num_employees': '', 'balance_sheet_total': '', 'annual_turnover': '',
    'accounting_standard': '1',
}

def rec(**overrides):
    return {**_BASE, **overrides}


# ---------------------------------------------------------------------------
# CY0011_TYPE — national identifier type valid for country
# ---------------------------------------------------------------------------

class TestNationalIdType:
    def test_valid_country_specific_type(self):
        findings = validate_record(rec(), 1)
        assert not errors(findings, 'CY0011_TYPE')

    def test_valid_generic_type_for_any_country(self):
        # GEN_TAX_CD is a generic code — valid for any country
        r = rec(national_id='123456789', national_id_type='GEN_TAX_CD', country='DE')
        assert not errors(validate_record(r, 1), 'CY0011_TYPE')

    def test_generic_type_accepted_for_non_eu_country(self):
        r = rec(national_id='123456789', national_id_type='GEN_TAX_CD', country='JP')
        assert not errors(validate_record(r, 1), 'CY0011_TYPE')

    def test_wrong_country_type_raises_error(self):
        # BE_OND_CD is only valid for BE, not DE
        r = rec(national_id='0203201340', national_id_type='BE_OND_CD', country='DE')
        assert errors(validate_record(r, 1), 'CY0011_TYPE')

    def test_de_type_rejected_for_be(self):
        r = rec(national_id='DE123456789', national_id_type='DE_VAT_CD', country='BE',
                postal_code='1000', legal_form='BE610')
        assert errors(validate_record(r, 1), 'CY0011_TYPE')

    def test_missing_type_when_nat_id_present_raises_error(self):
        r = rec(national_id='HRB1-A2016', national_id_type='')
        assert errors(validate_record(r, 1), 'CY0011_TYPE')

    def test_unknown_country_no_type_restriction(self):
        # Country not in our list — any type code accepted
        r = rec(national_id='ABC123', national_id_type='GEN_OTHER_CD', country='JP',
                postal_code='100-0001')
        assert not errors(validate_record(r, 1), 'CY0011_TYPE')

    def test_notappl_nat_id_skips_type_check(self):
        # NOT_APPL national_id → type check must not fire
        r = rec(national_id='NOT_APPL', national_id_type='')
        assert not errors(validate_record(r, 1), 'CY0011_TYPE')


# ---------------------------------------------------------------------------
# CY0011_FMT — national identifier format
# ---------------------------------------------------------------------------

class TestNationalIdFormat:
    def test_valid_de_trade_register(self):
        # HRB1-A2016 matches DE_TRD_RGSTR_CD pattern
        assert not errors(validate_record(rec(), 1), 'CY0011_FMT')

    def test_invalid_de_trade_register(self):
        r = rec(national_id='INVALID_REG')
        assert errors(validate_record(r, 1), 'CY0011_FMT')

    def test_valid_de_vat(self):
        r = rec(national_id='DE123456789', national_id_type='DE_VAT_CD')
        assert not errors(validate_record(r, 1), 'CY0011_FMT')

    def test_invalid_de_vat(self):
        # DE_VAT_CD requires DE + 9 digits; missing DE prefix
        r = rec(national_id='123456789', national_id_type='DE_VAT_CD')
        assert errors(validate_record(r, 1), 'CY0011_FMT')

    def test_valid_at_ident(self):
        r = rec(national_id='ATU12345678', national_id_type='AT_IDENT_CD',
                country='AT', postal_code='1010', legal_form='AT202')
        assert not errors(validate_record(r, 1), 'CY0011_FMT')

    def test_invalid_at_ident(self):
        r = rec(national_id='12345678', national_id_type='AT_IDENT_CD',
                country='AT', postal_code='1010', legal_form='AT202')
        assert errors(validate_record(r, 1), 'CY0011_FMT')

    def test_valid_be_ond(self):
        r = rec(national_id='0203201340', national_id_type='BE_OND_CD',
                country='BE', postal_code='1000', legal_form='BE610')
        assert not errors(validate_record(r, 1), 'CY0011_FMT')

    def test_invalid_be_ond(self):
        r = rec(national_id='INVALID', national_id_type='BE_OND_CD',
                country='BE', postal_code='1000', legal_form='BE610')
        assert errors(validate_record(r, 1), 'CY0011_FMT')

    def test_valid_fr_siren(self):
        r = rec(national_id='542051180', national_id_type='FR_SIREN_CD',
                country='FR', postal_code='75001', legal_form='FR001')
        assert not errors(validate_record(r, 1), 'CY0011_FMT')

    def test_invalid_fr_siren(self):
        r = rec(national_id='54205', national_id_type='FR_SIREN_CD',
                country='FR', postal_code='75001', legal_form='FR001')
        assert errors(validate_record(r, 1), 'CY0011_FMT')

    def test_valid_gb_crn(self):
        r = rec(national_id='01234567', national_id_type='GB_CRN_CD',
                country='GB', postal_code='E14 5AB', legal_form='GB300')
        assert not errors(validate_record(r, 1), 'CY0011_FMT')

    def test_invalid_gb_crn(self):
        r = rec(national_id='1234', national_id_type='GB_CRN_CD',
                country='GB', postal_code='E14 5AB', legal_form='GB300')
        assert errors(validate_record(r, 1), 'CY0011_FMT')

    def test_valid_mx_rfc(self):
        r = rec(national_id='GFI-920961-IL7', national_id_type='MX_RFC_CD',
                country='MX', postal_code='06600', legal_form='NOT_APPL')
        assert not errors(validate_record(r, 1), 'CY0011_FMT')

    def test_invalid_mx_rfc(self):
        r = rec(national_id='INVALID-RFC', national_id_type='MX_RFC_CD',
                country='MX', postal_code='06600', legal_form='NOT_APPL')
        assert errors(validate_record(r, 1), 'CY0011_FMT')

    def test_valid_us_ein(self):
        r = rec(national_id='12-3456789', national_id_type='US_EIN_CD',
                country='US', postal_code='10001', legal_form='NOT_APPL')
        assert not errors(validate_record(r, 1), 'CY0011_FMT')

    def test_invalid_us_ein(self):
        r = rec(national_id='123456789', national_id_type='US_EIN_CD',
                country='US', postal_code='10001', legal_form='NOT_APPL')
        assert errors(validate_record(r, 1), 'CY0011_FMT')

    def test_valid_ca_bn(self):
        r = rec(national_id='123456789', national_id_type='CA_BN_CD',
                country='CA', postal_code='M5H 2N2', legal_form='NOT_APPL')
        assert not errors(validate_record(r, 1), 'CY0011_FMT')

    def test_invalid_ca_bn(self):
        r = rec(national_id='12345', national_id_type='CA_BN_CD',
                country='CA', postal_code='M5H 2N2', legal_form='NOT_APPL')
        assert errors(validate_record(r, 1), 'CY0011_FMT')

    def test_type_without_format_pattern_skips_format_check(self):
        # AT_NOTAP_CD has no format regex — should not raise CY0011_FMT
        r = rec(national_id='NOTAPPLICABLE', national_id_type='AT_NOTAP_CD',
                country='AT', postal_code='1010', legal_form='AT202')
        assert not errors(validate_record(r, 1), 'CY0011_FMT')

    def test_generic_code_without_format_skips_format_check(self):
        r = rec(national_id='SOMEVALUE', national_id_type='GEN_OTHER_CD')
        assert not errors(validate_record(r, 1), 'CY0011_FMT')


# ---------------------------------------------------------------------------
# CY0120 — legal form codelist validation
# ---------------------------------------------------------------------------

class TestLegalForm:
    def test_valid_legal_form_de(self):
        assert not errors(validate_record(rec(), 1), 'CY0120')

    def test_valid_legal_form_at(self):
        r = rec(country='AT', postal_code='1010', legal_form='AT202',
                national_id='ATU12345678', national_id_type='AT_IDENT_CD')
        assert not errors(validate_record(r, 1), 'CY0120')

    def test_invalid_legal_form_raises_error(self):
        r = rec(legal_form='INVALID_FORM')
        assert errors(validate_record(r, 1), 'CY0120')

    def test_notappl_legal_form_accepted(self):
        r = rec(legal_form='NOT_APPL')
        assert not errors(validate_record(r, 1), 'CY0120')

    def test_empty_legal_form_raises_error(self):
        r = rec(legal_form='')
        assert errors(validate_record(r, 1), 'CY0120')

    def test_made_up_code_rejected(self):
        r = rec(legal_form='XX999')
        assert errors(validate_record(r, 1), 'CY0120')

    def test_all_countries_sample_valid_forms(self):
        cases = [
            ('AT', 'AT202', 'ATU12345678', 'AT_IDENT_CD', '1010'),
            ('BE', 'BE610', '0203201340', 'BE_OND_CD', '1000'),
            ('FR', 'FR001', '542051180', 'FR_SIREN_CD', '75001'),
            ('GB', 'GB300', '01234567', 'GB_CRN_CD', 'E14 5AB'),
        ]
        for country, lf, nat_id, nat_id_type, postal in cases:
            r = rec(country=country, legal_form=lf, national_id=nat_id,
                    national_id_type=nat_id_type, postal_code=postal)
            assert not errors(validate_record(r, 1), 'CY0120'), \
                f'CY0120 should not fire for country={country}, legal_form={lf}'

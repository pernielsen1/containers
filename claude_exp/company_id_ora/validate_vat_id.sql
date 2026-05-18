-- validate_vat_id.sql
-- Oracle PL/SQL package implementing VAT ID validation.
-- Port of the MySQL validate_vat_id.sql / snippets_copy/company_identifiers.py.
--
-- PREREQUISITE: validate_company_id.sql must have been run first.
-- Calls COMPANY_ID_PKG helper functions and validate_company_id for the fallback path.
--
-- Countries with dedicated VAT rules (handled inline):
--   AT  ATU + 8 digits
--   BE  BE + 10-digit modulus-97, or EU + 1-4 digits
--   CH  CH/CHE + 9-digit modulus-11 (full sum % 11 = 0)
--   DE  DE + 9 digits
--   ES  ES* + 8-digit modulus-10
--   EU  EU + 1-4 digits
--   FR  FR + 2 key digits + SIREN (mod-10)
--   MC  FR + 11 digits (Monaco)
--   GB  GB + 9 digits
--   LU  LU + 8 digits
--   NL  NL + 9 digits + B + 2 digits
--   PT  PT + 9-digit modulus-11
--   RO  RO + 2-10 digits
--   SE  SE + 10-digit org-no + "01" (mod-10)
--   SK  SK + 10 digits
--
-- Fallback: strip country-code prefix, delegate to COMPANY_ID_PKG.validate_company_id.
-- Covers: BG CA CZ DK EE FI GR HR HU IE IT LI LT LV MT MX NO PL SI (and unknown).

CREATE OR REPLACE PACKAGE VAT_ID_PKG AS

    PROCEDURE validate_vat_id(
        p_CNTRY  IN  VARCHAR2,
        p_ID     IN  VARCHAR2,
        p_result OUT NUMBER
    );

END VAT_ID_PKG;
/

CREATE OR REPLACE PACKAGE BODY VAT_ID_PKG AS

    PROCEDURE validate_vat_id(
        p_CNTRY  IN  VARCHAR2,
        p_ID     IN  VARCHAR2,
        p_result OUT NUMBER
    ) IS
        v_s        VARCHAR2(200);
        v_before   VARCHAR2(50);
        v_number   VARCHAR2(50);
        v_after    VARCHAR2(50);
        v_len      PLS_INTEGER;
        v_excl     VARCHAR2(50);
        v_expected NUMBER;
        v_rest     NUMBER;
        v_chk      NUMBER;
        v_inner    NUMBER;
    BEGIN
        p_result := 0;

        v_s      := COMPANY_ID_PKG.fn_cid_clean(p_ID);
        v_before := COMPANY_ID_PKG.fn_cid_before(v_s);
        v_number := COMPANY_ID_PKG.fn_cid_number(v_s);
        v_after  := COMPANY_ID_PKG.fn_cid_after(v_s);
        v_len    := NVL(LENGTH(v_number), 0);

        CASE p_CNTRY

            -- AT: ATU + 8 digits, no check digit
            WHEN 'AT' THEN
                IF UPPER(v_before) = 'ATU' AND v_len = 8 AND v_after IS NULL THEN
                    p_result := 1;
                END IF;

            -- BE: BE + 10-digit modulus-97, or EU + 1-4 digits
            WHEN 'BE' THEN
                IF UPPER(v_before) = 'EU' AND v_len BETWEEN 1 AND 4 AND v_after IS NULL THEN
                    p_result := 1;
                ELSIF UPPER(v_before) = 'BE' AND v_len = 10 AND v_after IS NULL THEN
                    IF (97 - MOD(TO_NUMBER(SUBSTR(v_number, 1, 8)), 97))
                        = TO_NUMBER(SUBSTR(v_number, 9, 2))
                    THEN
                        p_result := 1;
                    END IF;
                END IF;

            -- CH: CH/CHE prefix + 9-digit modulus-11; full weighted sum must be divisible by 11
            WHEN 'CH' THEN
                IF UPPER(SUBSTR(v_before, 1, 2)) = 'CH' AND v_len = 9 AND v_after IS NULL THEN
                    IF MOD(COMPANY_ID_PKG.fn_wsum(v_number, 5,4,3,2,7,6,5,4,1,0), 11) = 0 THEN
                        p_result := 1;
                    END IF;
                END IF;

            -- DE: DE + 9 digits, no check digit
            WHEN 'DE' THEN
                IF UPPER(v_before) = 'DE' AND v_len = 9 AND v_after IS NULL THEN
                    p_result := 1;
                END IF;

            -- ES: ES* prefix + 8-digit modulus-10
            WHEN 'ES' THEN
                IF UPPER(SUBSTR(v_before, 1, 2)) = 'ES' AND v_len = 8 AND v_after IS NULL THEN
                    v_excl     := SUBSTR(v_number, 1, 7);
                    v_expected := TO_NUMBER(SUBSTR(v_number, 8, 1));
                    IF COMPANY_ID_PKG.fn_modulus10_calc(v_excl) = v_expected THEN
                        p_result := 1;
                    END IF;
                END IF;

            -- EU: EU + 1-4 digits, no check digit
            WHEN 'EU' THEN
                IF UPPER(v_before) = 'EU' AND v_len BETWEEN 1 AND 4 AND v_after IS NULL THEN
                    p_result := 1;
                END IF;

            -- FR: FR + 2 key digits + SIREN (9 digits), mod-10 on SIREN
            WHEN 'FR' THEN
                IF UPPER(v_before) = 'FR' AND v_len = 11 AND v_after IS NULL THEN
                    -- v_number positions 1-2 = key digits, 3-11 = SIREN
                    v_excl     := SUBSTR(v_number, 3, 8);           -- SIREN first 8
                    v_expected := TO_NUMBER(SUBSTR(v_number, 11, 1)); -- SIREN check digit
                    IF COMPANY_ID_PKG.fn_modulus10_calc(v_excl) = v_expected THEN
                        p_result := 1;
                    END IF;
                END IF;

            -- MC: Monaco uses FR prefix + 11 digits, no further check
            WHEN 'MC' THEN
                IF UPPER(v_before) = 'FR' AND v_len = 11 AND v_after IS NULL THEN
                    p_result := 1;
                END IF;

            -- GB: GB + 9 digits, no check digit
            WHEN 'GB' THEN
                IF UPPER(v_before) = 'GB' AND v_len = 9 AND v_after IS NULL THEN
                    p_result := 1;
                END IF;

            -- LU: LU + 8 digits, no check digit
            WHEN 'LU' THEN
                IF UPPER(v_before) = 'LU' AND v_len = 8 AND v_after IS NULL THEN
                    p_result := 1;
                END IF;

            -- NL: NL + 9 digits + B + 2 digits = 14 chars total
            -- 'B' survives fn_cid_clean (only . - ( ) space removed)
            WHEN 'NL' THEN
                IF NVL(LENGTH(v_s), 0) = 14
                    AND UPPER(SUBSTR(v_s, 1, 2)) = 'NL'
                    AND REGEXP_LIKE(SUBSTR(v_s, 3, 9), '^[0-9]{9}$')
                    AND UPPER(SUBSTR(v_s, 12, 1)) = 'B'
                    AND REGEXP_LIKE(SUBSTR(v_s, 13, 2), '^[0-9]{2}$')
                THEN
                    p_result := 1;
                END IF;

            -- PT: PT + 9-digit modulus-11, weights [9,8,7,6,5,4,3,2]
            WHEN 'PT' THEN
                IF UPPER(v_before) = 'PT' AND v_len = 9 AND v_after IS NULL THEN
                    v_excl     := SUBSTR(v_number, 1, 8);
                    v_expected := TO_NUMBER(SUBSTR(v_number, 9, 1));
                    v_rest     := MOD(COMPANY_ID_PKG.fn_wsum(v_excl, 9,8,7,6,5,4,3,2,0,0), 11);
                    IF    v_rest = 0 THEN v_chk := 0;
                    ELSIF v_rest = 1 THEN v_chk := 0;
                    ELSE                  v_chk := 11 - v_rest;
                    END IF;
                    IF v_chk = v_expected THEN p_result := 1; END IF;
                END IF;

            -- RO: RO + 2-10 digits, no check digit
            WHEN 'RO' THEN
                IF UPPER(v_before) = 'RO' AND v_len BETWEEN 2 AND 10 AND v_after IS NULL THEN
                    p_result := 1;
                END IF;

            -- SE: SE + 10-digit org-no + "01"; mod-10 on org-no
            WHEN 'SE' THEN
                IF UPPER(v_before) = 'SE' AND v_len = 12 AND v_after IS NULL THEN
                    IF SUBSTR(v_number, 11, 2) = '01' THEN
                        v_excl     := SUBSTR(v_number, 1, 9);           -- org-no first 9
                        v_expected := TO_NUMBER(SUBSTR(v_number, 10, 1)); -- org-no check digit
                        IF COMPANY_ID_PKG.fn_modulus10_calc(v_excl) = v_expected THEN
                            p_result := 1;
                        END IF;
                    END IF;
                END IF;

            -- SK: SK + 10 digits, no check digit
            WHEN 'SK' THEN
                IF UPPER(v_before) = 'SK' AND v_len = 10 AND v_after IS NULL THEN
                    p_result := 1;
                END IF;

            -- EE: EE + exactly 9 digits, no check digit
            WHEN 'EE' THEN
                IF UPPER(v_before) = 'EE' AND v_len = 9 AND v_after IS NULL THEN
                    p_result := 1;
                END IF;

            -- LT: LT + 9-12 digits, no check digit
            WHEN 'LT' THEN
                IF UPPER(v_before) = 'LT' AND v_len BETWEEN 9 AND 12 AND v_after IS NULL THEN
                    p_result := 1;
                END IF;

            -- Fallback: country-code prefix + company-ID number
            -- Strips the 2-char country prefix and delegates to company-ID validation.
            ELSE
                IF UPPER(v_before) = UPPER(p_CNTRY) AND v_len > 0 THEN
                    COMPANY_ID_PKG.validate_company_id(p_CNTRY, v_number, v_inner);
                    p_result := NVL(v_inner, 0);
                END IF;

        END CASE;

    EXCEPTION
        WHEN OTHERS THEN p_result := 0;
    END validate_vat_id;

END VAT_ID_PKG;
/

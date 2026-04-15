-- validate_vat_id.sql
-- Stored procedure implementing validate_VAT_ID from snippets_copy/company_identifiers.py
--
-- PREREQUISITE: validate_company_id.sql must have been run first.
-- This procedure reuses the helper functions defined there:
--   fn_cid_clean, fn_cid_before, fn_cid_number, fn_cid_after,
--   fn_modulus10_calc, fn_wsum
-- and calls the procedure validate_company_id for the fallback path.
--
-- Logic mirrors validate_VAT_ID(s, country_code):
--   1. If a specific _VAT_ID definition exists → use its algorithm.
--   2. Otherwise → strip the 2-char country-code prefix, validate the
--      remaining number with the country's company-ID algorithm.
--
-- Countries with dedicated VAT rules (handled inline in CASE):
--   AT  ATU + 8 digits, no check digit
--   BE  BE  + 10-digit modulus-97
--   CH  CH  + 9-digit modulus-11  (weights 5,4,3,2,7,6,5,4,1 — full sum % 11 = 0)
--   DE  DE  + 9 digits, no check digit
--   ES  ES* + 8-digit modulus-10  (prefix starting with ES, TBD letter types)
--   EU  EU  + 1-4 digits, no check digit
--   FR  FR  + 2 key digits + 9-digit SIREN (mod-10 on SIREN)
--   MC  FR  + 11 digits (Monaco uses FR prefix, no further check)
--   GB  GB  + 9 digits, no check digit
--   LU  LU  + 8 digits, no check digit
--   NL  NL  + 9 digits + B + 2 digits = 14 chars total
--   PT  PT  + 9-digit modulus-11  (weights 9,8,7,6,5,4,3,2)
--   RO  RO  + 2-10 digits, no check digit
--   SE  SE  + 10-digit org-no + "01"  (mod-10 on org-no)
--   SK  SK  + 10 digits, no check digit
--
-- Fallback (ELSE): country-code prefix + company-ID number
--   BG CA CZ DK EE FI GR HR HU IE IT LI LT LV MT MX NO PL SI

DELIMITER //

DROP PROCEDURE IF EXISTS validate_vat_id //
CREATE PROCEDURE validate_vat_id(
    IN  p_CNTRY  CHAR(2),
    IN  p_ID     VARCHAR(100),
    OUT p_result TINYINT          -- 1 = OK, 0 = FAIL
)
BEGIN
    DECLARE v_s        VARCHAR(200);   -- cleaned input
    DECLARE v_before   VARCHAR(50);    -- leading non-digit chars
    DECLARE v_number   VARCHAR(50);    -- digit block
    DECLARE v_after    VARCHAR(50);    -- trailing non-digit chars
    DECLARE v_len      INT;            -- length of v_number
    DECLARE v_excl     VARCHAR(50);    -- number WITHOUT check digit
    DECLARE v_expected INT;            -- expected check digit
    DECLARE v_rest     INT;            -- mod-11 remainder
    DECLARE v_chk      INT;            -- computed check digit
    DECLARE v_inner    TINYINT;        -- result from inner validate_company_id call

    SET p_result = 0;   -- default: FAIL

    SET v_s      = fn_cid_clean(p_ID);
    SET v_before = fn_cid_before(v_s);
    SET v_number = fn_cid_number(v_s);
    SET v_after  = fn_cid_after(v_s);
    SET v_len    = CHAR_LENGTH(v_number);

    CASE p_CNTRY

        -- ── AT: ATU + 8 digits, no check digit ───────────────────────────────
        -- Python: AT_VAT_ID → validate_vat_std + validate_just_numeric
        --   before_list=['ATU',''], country='AT', len=8
        --   validate_vat_std checks before[0:2]=='AT' → only 'ATU' prefix satisfies that
        WHEN 'AT' THEN
            IF UPPER(v_before) = 'ATU' AND v_len = 8 AND v_after = '' THEN
                SET p_result = 1;
            END IF;

        -- ── BE: BE + 10-digit modulus-97, or EU + 1-4 digits ────────────────
        -- Python: BE_VAT_ID → validate_vat_std + validate_modulus97, len=10
        --   validate_vat_std checks s[0:2]=='EU' first and, if so, reroutes to
        --   validate_VAT_ID(s,'EU'): EU prefix + 1-4 digits, no check digit.
        --   Otherwise: BE prefix + 10 digits, 97 - (first_8 % 97) == last 2.
        WHEN 'BE' THEN
            IF UPPER(v_before) = 'EU' AND v_len BETWEEN 1 AND 4 AND v_after = '' THEN
                SET p_result = 1;
            ELSEIF UPPER(v_before) = 'BE' AND v_len = 10 AND v_after = '' THEN
                IF (97 - (CAST(LEFT(v_number, 8) AS UNSIGNED) % 97))
                    = CAST(SUBSTR(v_number, 9, 2) AS UNSIGNED)
                THEN
                    SET p_result = 1;
                END IF;
            END IF;

        -- ── CH: CH + 9-digit modulus-11, weights [5,4,3,2,7,6,5,4,1] ──────────
        -- Python: CH_VAT_ID → validate_vat_std + validate_modulus11, len=9
        --   Prefix: first 2 chars must be 'CH' (accepts both 'CH' and 'CHE').
        --   All 9 weights are applied to all 9 digits; the weighted sum must be
        --   divisible by 11 (remainder = 0 → valid).
        WHEN 'CH' THEN
            IF UPPER(LEFT(v_before, 2)) = 'CH' AND v_len = 9 AND v_after = '' THEN
                IF fn_wsum(v_number, 5,4,3,2,7,6,5,4,1, 0) % 11 = 0 THEN
                    SET p_result = 1;
                END IF;
            END IF;

        -- ── DE: DE + 9 digits, no check digit ────────────────────────────────
        -- Python: DE_VAT_ID → validate_vat_std + validate_just_numeric, len=9
        WHEN 'DE' THEN
            IF UPPER(v_before) = 'DE' AND v_len = 9 AND v_after = '' THEN
                SET p_result = 1;
            END IF;

        -- ── ES: ES* prefix + 8-digit modulus-10 ──────────────────────────────
        -- Python: ES_VAT_ID → validate_vat_std + validate_modulus10, len=8
        --   before_list_TBD (not enforced); validate_vat_std passes just the 8-digit
        --   number to validate_modulus10 regardless of any NIF letter prefix.
        --   Accepts any prefix whose first 2 chars are 'ES'.
        WHEN 'ES' THEN
            IF UPPER(LEFT(v_before, 2)) = 'ES' AND v_len = 8 AND v_after = '' THEN
                SET v_excl     = LEFT(v_number, 7);
                SET v_expected = CAST(SUBSTR(v_number, 8, 1) AS UNSIGNED);
                IF fn_modulus10_calc(v_excl) = v_expected THEN SET p_result = 1; END IF;
            END IF;

        -- ── EU: EU + 1-4 digits ───────────────────────────────────────────────
        -- Python: EU_VAT_ID → validate_just_numeric, before_list='EU', min_len=1, len=4
        WHEN 'EU' THEN
            IF UPPER(v_before) = 'EU' AND v_len BETWEEN 1 AND 4 AND v_after = '' THEN
                SET p_result = 1;
            END IF;

        -- ── FR: FR + 2 key chars + SIREN (9 digits), mod-10 on SIREN ──────────
        -- Python: FR_VAT_ID → validate_france_vat, before_list=['FR'], len=11
        --   Cleaned format: 'FR' + 11 digits (total 13 chars in v_s)
        --   SIREN = v_number[3:11]  (positions 3-11 of the 11-digit block)
        --   Check: mod-10 of SIREN[1:8] == SIREN[9]
        WHEN 'FR' THEN
            IF UPPER(v_before) = 'FR' AND v_len = 11 AND v_after = '' THEN
                -- v_number: pos 1-2 = key digits, pos 3-11 = SIREN
                SET v_excl     = SUBSTR(v_number, 3, 8);          -- SIREN first 8 digits
                SET v_expected = CAST(SUBSTR(v_number, 11, 1) AS UNSIGNED); -- SIREN check digit
                IF fn_modulus10_calc(v_excl) = v_expected THEN SET p_result = 1; END IF;
            END IF;

        -- ── MC: Monaco uses FR prefix + 11 digits, no further check ──────────
        -- Python: MC_VAT_ID → validate_monaco_vat → just get_before_number_after
        WHEN 'MC' THEN
            IF UPPER(v_before) = 'FR' AND v_len = 11 AND v_after = '' THEN
                SET p_result = 1;
            END IF;

        -- ── GB: GB + 9 digits, no check digit ────────────────────────────────
        -- Python: GB_VAT_ID → validate_vat_std + validate_just_numeric, len=9
        WHEN 'GB' THEN
            IF UPPER(v_before) = 'GB' AND v_len = 9 AND v_after = '' THEN
                SET p_result = 1;
            END IF;

        -- ── LU: LU + 8 digits, no check digit ────────────────────────────────
        -- Python: LU_VAT_ID → validate_just_numeric, before_list=['LU'], len=8
        WHEN 'LU' THEN
            IF UPPER(v_before) = 'LU' AND v_len = 8 AND v_after = '' THEN
                SET p_result = 1;
            END IF;

        -- ── NL: NL + 9 digits + B + 2 digits = 14 chars total ────────────────
        -- Python: NL_VAT_ID → validate_vat_nl
        --   s[0:2]='NL', s[2:11]=9 digits, s[11:12]='B', s[12:14]=2 digits
        --   Note: 'B' survives fn_cid_clean (only . - ( ) space are removed)
        WHEN 'NL' THEN
            IF CHAR_LENGTH(v_s) = 14
                AND UPPER(LEFT(v_s, 2))       = 'NL'
                AND SUBSTR(v_s, 3, 9)          REGEXP '^[0-9]{9}$'
                AND UPPER(SUBSTR(v_s, 12, 1)) = 'B'
                AND SUBSTR(v_s, 13, 2)         REGEXP '^[0-9]{2}$'
            THEN
                SET p_result = 1;
            END IF;

        -- ── PT: PT + 9-digit modulus-11, weights [9,8,7,6,5,4,3,2] ──────────
        -- Python: PT_VAT_ID → validate_vat_std + validate_modulus11, len=9
        --   Same weights and check-digit logic as PT_COMPANY_ID
        WHEN 'PT' THEN
            IF UPPER(v_before) = 'PT' AND v_len = 9 AND v_after = '' THEN
                SET v_excl     = LEFT(v_number, 8);
                SET v_expected = CAST(SUBSTR(v_number, 9, 1) AS UNSIGNED);
                SET v_rest = fn_wsum(v_excl, 9,8,7,6,5,4,3,2, 0,0) % 11;
                IF v_rest = 0 THEN SET v_chk = 0;
                ELSEIF v_rest = 1 THEN SET v_chk = 0;
                ELSE SET v_chk = 11 - v_rest;
                END IF;
                IF v_chk = v_expected THEN SET p_result = 1; END IF;
            END IF;

        -- ── RO: RO + 2-10 digits, no check digit ─────────────────────────────
        -- Python: RO_VAT_ID → validate_romania_vat → get_before_number_after
        --   before_list=['RO'], min_len=2, len=10
        WHEN 'RO' THEN
            IF UPPER(v_before) = 'RO' AND v_len BETWEEN 2 AND 10 AND v_after = '' THEN
                SET p_result = 1;
            END IF;

        -- ── SE: SE + 10-digit org-no + "01", mod-10 on org-no ────────────────
        -- Python: SE_VAT_ID → validate_sweden_vat, before_list=['SE'], len=12
        --   Cleaned: 'SE' + 12 digits (14 chars total in v_s)
        --   org_no = v_number[1:10]  (first 10 digits of the 12-digit block)
        --   last2  = v_number[11:12] must be '01'
        --   Check: mod-10 of org_no[1:9] == org_no[10]
        WHEN 'SE' THEN
            IF UPPER(v_before) = 'SE' AND v_len = 12 AND v_after = '' THEN
                IF SUBSTR(v_number, 11, 2) = '01' THEN
                    SET v_excl     = LEFT(v_number, 9);            -- org-no first 9 digits
                    SET v_expected = CAST(SUBSTR(v_number, 10, 1) AS UNSIGNED); -- org-no check digit
                    IF fn_modulus10_calc(v_excl) = v_expected THEN SET p_result = 1; END IF;
                END IF;
            END IF;

        -- ── SK: SK + 10 digits, no check digit ───────────────────────────────
        -- Python: SK_VAT_ID → validate_just_numeric, before_list=['SK'], len=10
        WHEN 'SK' THEN
            IF UPPER(v_before) = 'SK' AND v_len = 10 AND v_after = '' THEN
                SET p_result = 1;
            END IF;

        -- ── Fallback: country-code prefix + company-ID number ────────────────
        -- Python: no _VAT_ID entry → validate_VAT_ID strips the 2-char country
        --   prefix and passes just the digit block to the company-ID algorithm.
        -- Covers: BG CA CZ DK EE FI GR HR HU IE IT LI LT LV MT MX NO PL SI
        --   and any unknown country.
        ELSE
            IF UPPER(v_before) = UPPER(p_CNTRY) AND v_len > 0 THEN
                CALL validate_company_id(p_CNTRY, v_number, v_inner);
                SET p_result = IFNULL(v_inner, 0);
            END IF;

    END CASE;
END //

DELIMITER ;

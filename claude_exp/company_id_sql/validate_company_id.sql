-- validate_company_id.sql
-- Stored procedure + helper functions implementing validate_COMPANY_ID
-- from snippets_copy/company_identifiers.py

DELIMITER //

-- ─────────────────────────────────────────────────────────────────────────────
-- HELPER FUNCTIONS
-- ─────────────────────────────────────────────────────────────────────────────

-- Remove . - ( ) and spaces (mirrors clean_str in Python)
DROP FUNCTION IF EXISTS fn_cid_clean //
CREATE FUNCTION fn_cid_clean(s VARCHAR(200)) RETURNS VARCHAR(200) DETERMINISTIC
BEGIN
    RETURN REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(s, '.', ''), '-', ''), '(', ''), ')', ''), ' ', '');
END //

-- Extract leading non-digit prefix ("before")
DROP FUNCTION IF EXISTS fn_cid_before //
CREATE FUNCTION fn_cid_before(s VARCHAR(200)) RETURNS VARCHAR(50) DETERMINISTIC
BEGIN
    DECLARE i INT DEFAULT 1;
    WHILE i <= CHAR_LENGTH(s) AND NOT (SUBSTR(s, i, 1) BETWEEN '0' AND '9') DO
        SET i = i + 1;
    END WHILE;
    RETURN LEFT(s, i - 1);
END //

-- Extract the run of digits in the middle ("number")
DROP FUNCTION IF EXISTS fn_cid_number //
CREATE FUNCTION fn_cid_number(s VARCHAR(200)) RETURNS VARCHAR(100) DETERMINISTIC
BEGIN
    DECLARE i INT DEFAULT 1;
    DECLARE j INT;
    WHILE i <= CHAR_LENGTH(s) AND NOT (SUBSTR(s, i, 1) BETWEEN '0' AND '9') DO
        SET i = i + 1;
    END WHILE;
    SET j = i;
    WHILE j <= CHAR_LENGTH(s) AND (SUBSTR(s, j, 1) BETWEEN '0' AND '9') DO
        SET j = j + 1;
    END WHILE;
    RETURN SUBSTR(s, i, j - i);
END //

-- Extract trailing non-digit suffix ("after")
DROP FUNCTION IF EXISTS fn_cid_after //
CREATE FUNCTION fn_cid_after(s VARCHAR(200)) RETURNS VARCHAR(50) DETERMINISTIC
BEGIN
    DECLARE i INT DEFAULT 1;
    WHILE i <= CHAR_LENGTH(s) AND NOT (SUBSTR(s, i, 1) BETWEEN '0' AND '9') DO
        SET i = i + 1;
    END WHILE;
    WHILE i <= CHAR_LENGTH(s) AND (SUBSTR(s, i, 1) BETWEEN '0' AND '9') DO
        SET i = i + 1;
    END WHILE;
    RETURN SUBSTR(s, i);
END //

-- Luhn-style modulus-10 check digit.
-- Input: all digits EXCEPT the check digit.
-- Returns: expected check digit (0-9).
DROP FUNCTION IF EXISTS fn_modulus10_calc //
CREATE FUNCTION fn_modulus10_calc(s VARCHAR(50)) RETURNS INT DETERMINISTIC
BEGIN
    DECLARE res INT DEFAULT 0;
    DECLARE n   INT;
    DECLARE i   INT DEFAULT 1;
    DECLARE len INT;
    SET len = CHAR_LENGTH(s);
    WHILE i <= len DO
        SET n = CAST(SUBSTR(s, len - i + 1, 1) AS UNSIGNED);
        -- Python i starts at 0; even positions (0,2,4…) from the right get doubled
        -- SQL i starts at 1; same effect when using (i-1) % 2
        IF (i - 1) % 2 = 0 THEN
            SET n = n * 2;
            IF n > 9 THEN SET n = n - 9; END IF;
        END IF;
        SET res = res + n;
        SET i = i + 1;
    END WHILE;
    SET res = 10 - (res % 10);
    IF res = 10 THEN SET res = 0; END IF;
    RETURN res;
END //

-- Weighted sum for modulus-11 (up to 10 weights; pass 0 for unused slots).
-- Mirrors calc_modulus11_remainder: cycles through weights for each digit.
DROP FUNCTION IF EXISTS fn_wsum //
CREATE FUNCTION fn_wsum(
    s   VARCHAR(50),
    w1  INT, w2  INT, w3  INT, w4  INT, w5  INT,
    w6  INT, w7  INT, w8  INT, w9  INT, w10 INT
) RETURNS INT DETERMINISTIC
BEGIN
    DECLARE i   INT DEFAULT 1;
    DECLARE len INT;
    DECLARE wi  INT;
    DECLARE res INT DEFAULT 0;
    SET len = CHAR_LENGTH(s);
    WHILE i <= len DO
        SET wi = CASE ((i - 1) % 10)
            WHEN 0 THEN w1  WHEN 1 THEN w2  WHEN 2 THEN w3
            WHEN 3 THEN w4  WHEN 4 THEN w5  WHEN 5 THEN w6
            WHEN 6 THEN w7  WHEN 7 THEN w8  WHEN 8 THEN w9
            ELSE w10
        END;
        SET res = res + CAST(SUBSTR(s, i, 1) AS UNSIGNED) * wi;
        SET i = i + 1;
    END WHILE;
    RETURN res;
END //

-- ISO 7064 Mod-11/10 check digit (used for HR OIB, 11-digit number).
-- Input: first 10 digits (excl check digit). Returns expected check digit.
DROP FUNCTION IF EXISTS fn_iso7064_calc //
CREATE FUNCTION fn_iso7064_calc(s VARCHAR(20)) RETURNS INT DETERMINISTIC
BEGIN
    DECLARE i         INT DEFAULT 1;
    DECLARE remainder INT DEFAULT 10;
    WHILE i <= 10 DO
        SET remainder = (remainder + CAST(SUBSTR(s, i, 1) AS UNSIGNED)) % 10;
        IF remainder = 0 THEN SET remainder = 10; END IF;
        SET remainder = (remainder * 2) % 11;
        SET i = i + 1;
    END WHILE;
    SET remainder = 11 - remainder;
    IF remainder = 10 THEN SET remainder = 0; END IF;
    RETURN remainder;
END //


-- ─────────────────────────────────────────────────────────────────────────────
-- MAIN PROCEDURE
-- ─────────────────────────────────────────────────────────────────────────────

DROP PROCEDURE IF EXISTS validate_company_id //
CREATE PROCEDURE validate_company_id(
    IN  p_CNTRY  CHAR(2),
    IN  p_ID     VARCHAR(100),
    OUT p_result TINYINT          -- 1 = OK, 0 = FAIL
)
BEGIN
    DECLARE v_s        VARCHAR(200);   -- cleaned input
    DECLARE v_before   VARCHAR(50);    -- leading non-digit chars
    DECLARE v_number   VARCHAR(50);    -- digit block
    DECLARE v_after    VARCHAR(50);    -- trailing non-digit chars
    DECLARE v_excl     VARCHAR(50);    -- number WITHOUT check digit
    DECLARE v_expected INT;            -- last digit (expected check digit)
    DECLARE v_chk      INT;            -- computed check digit
    DECLARE v_len      INT;            -- length of v_number
    DECLARE v_rest     INT;            -- mod11 remainder
    DECLARE v_rest2    INT;            -- second-round mod11 remainder (EE/BG/LT)

    SET p_result = 0;   -- default: FAIL

    -- ── Clean input ──────────────────────────────────────────────────────────
    SET v_s      = fn_cid_clean(p_ID);
    SET v_before = fn_cid_before(v_s);
    SET v_number = fn_cid_number(v_s);
    SET v_after  = fn_cid_after(v_s);
    SET v_len    = CHAR_LENGTH(v_number);

    CASE p_CNTRY

        -- ── SE – modulus 10, exactly 10 digits, no prefix/suffix ─────────────
        WHEN 'SE' THEN
            IF v_len = 10 AND v_before = '' AND v_after = '' THEN
                SET v_excl     = LEFT(v_number, 9);
                SET v_expected = CAST(SUBSTR(v_number, 10, 1) AS UNSIGNED);
                IF fn_modulus10_calc(v_excl) = v_expected THEN SET p_result = 1; END IF;
            END IF;

        -- ── DK – modulus 11, weights [2,7,6,5,4,3,2,1], 8 digits ────────────
        WHEN 'DK' THEN
            IF v_len = 8 AND v_before = '' AND v_after = '' THEN
                SET v_excl     = LEFT(v_number, 7);
                SET v_expected = CAST(SUBSTR(v_number, 8, 1) AS UNSIGNED);
                -- rest = weighted_sum % 11; check_digit = 11 - rest (rest≠0,1)
                SET v_rest = fn_wsum(v_excl, 2,7,6,5,4,3,2, 0,0,0) % 11;
                IF v_rest = 0 THEN SET v_chk = 0;
                ELSEIF v_rest = 1 THEN SET v_chk = 0;
                ELSE SET v_chk = 11 - v_rest;
                END IF;
                IF v_chk = v_expected THEN SET p_result = 1; END IF;
            END IF;

        -- ── NO – modulus 11, weights [3,2,7,6,5,4,3,2,1], 9 digits ──────────
        WHEN 'NO' THEN
            IF v_len = 9 AND v_before = '' AND v_after = '' THEN
                SET v_excl     = LEFT(v_number, 8);
                SET v_expected = CAST(SUBSTR(v_number, 9, 1) AS UNSIGNED);
                SET v_rest = fn_wsum(v_excl, 3,2,7,6,5,4,3,2, 0,0) % 11;
                IF v_rest = 0 THEN SET v_chk = 0;
                ELSEIF v_rest = 1 THEN SET v_chk = 0;
                ELSE SET v_chk = 11 - v_rest;
                END IF;
                IF v_chk = v_expected THEN SET p_result = 1; END IF;
            END IF;

        -- ── FI – modulus 11, weights [7,9,10,5,8,4,2,1], 8 digits, zfill ────
        WHEN 'FI' THEN
            -- FI can be given with fewer leading digits; pad to 8
            IF v_before = '' AND v_after = '' AND v_len BETWEEN 1 AND 8 THEN
                SET v_number   = LPAD(v_number, 8, '0');
                SET v_len      = 8;
                SET v_excl     = LEFT(v_number, 7);
                SET v_expected = CAST(SUBSTR(v_number, 8, 1) AS UNSIGNED);
                SET v_rest = fn_wsum(v_excl, 7,9,10,5,8,4,2, 0,0,0) % 11;
                IF v_rest = 0 THEN SET v_chk = 0;
                ELSEIF v_rest = 1 THEN SET v_chk = 0;
                ELSE SET v_chk = 11 - v_rest;
                END IF;
                IF v_chk = v_expected THEN SET p_result = 1; END IF;
            END IF;

        -- ── PT – modulus 11, weights [9,8,7,6,5,4,3,2], 9 digits ────────────
        WHEN 'PT' THEN
            IF v_len = 9 AND v_before = '' AND v_after = '' THEN
                SET v_excl     = LEFT(v_number, 8);
                SET v_expected = CAST(SUBSTR(v_number, 9, 1) AS UNSIGNED);
                SET v_rest = fn_wsum(v_excl, 9,8,7,6,5,4,3,2, 0,0) % 11;
                IF v_rest = 0 THEN SET v_chk = 0;
                ELSEIF v_rest = 1 THEN SET v_chk = 0;
                ELSE SET v_chk = 11 - v_rest;
                END IF;
                IF v_chk = v_expected THEN SET p_result = 1; END IF;
            END IF;

        -- ── CZ – modulus 11, weights [8,7,6,5,4,3,2], 8 digits
        --        check_digit_for_0 = 1 ─────────────────────────────────────
        WHEN 'CZ' THEN
            IF v_len = 8 AND v_before = '' AND v_after = '' THEN
                SET v_excl     = LEFT(v_number, 7);
                SET v_expected = CAST(SUBSTR(v_number, 8, 1) AS UNSIGNED);
                SET v_rest = fn_wsum(v_excl, 8,7,6,5,4,3,2, 0,0,0) % 11;
                IF v_rest = 0 THEN SET v_chk = 1;   -- special: 0→1
                ELSEIF v_rest = 1 THEN SET v_chk = 0;
                ELSE SET v_chk = 11 - v_rest;
                END IF;
                IF v_chk = v_expected THEN SET p_result = 1; END IF;
            END IF;

        -- ── GR – modulus 11, weights [256,128,64,32,16,8,4,2], 9 digits
        --        return_rest=True, return_10=0 ───────────────────────────────
        WHEN 'GR' THEN
            IF v_len = 9 AND v_before = '' AND v_after = '' THEN
                SET v_excl     = LEFT(v_number, 8);
                SET v_expected = CAST(SUBSTR(v_number, 9, 1) AS UNSIGNED);
                SET v_rest = fn_wsum(v_excl, 256,128,64,32,16,8,4,2, 0,0) % 11;
                -- return_rest=True: check digit IS the remainder
                -- return_10=0: if rest=10 return 0
                IF v_rest = 10 THEN SET v_chk = 0;
                ELSE SET v_chk = v_rest;
                END IF;
                IF v_chk = v_expected THEN SET p_result = 1; END IF;
            END IF;

        -- ── BG – modulus 11 with round-2 fallback, return_rest=True, 9 digits
        --        weights=[1,2,3,4,5,6,7,8]  round2=[3,4,5,6,7,8,9,10] ───────
        WHEN 'BG' THEN
            IF v_len = 9 AND v_before = '' AND v_after = '' THEN
                SET v_excl     = LEFT(v_number, 8);
                SET v_expected = CAST(SUBSTR(v_number, 9, 1) AS UNSIGNED);
                SET v_rest = fn_wsum(v_excl, 1,2,3,4,5,6,7,8, 0,0) % 11;
                IF v_rest = 10 THEN
                    SET v_rest2 = fn_wsum(v_excl, 3,4,5,6,7,8,9,10, 0,0) % 11;
                    IF v_rest2 = 10 THEN SET v_chk = 0;
                    ELSE SET v_chk = v_rest2;
                    END IF;
                ELSE
                    SET v_chk = v_rest;
                END IF;
                IF v_chk = v_expected THEN SET p_result = 1; END IF;
            END IF;

        -- ── EE – modulus 11 with round-2, return_rest=True, 8 digits
        --        weights=[1,2,3,4,5,6,7]  round2=[3,4,5,6,7,8,9] ────────────
        WHEN 'EE' THEN
            IF v_len = 8 AND v_before = '' AND v_after = '' THEN
                SET v_excl     = LEFT(v_number, 7);
                SET v_expected = CAST(SUBSTR(v_number, 8, 1) AS UNSIGNED);
                SET v_rest = fn_wsum(v_excl, 1,2,3,4,5,6,7, 0,0,0) % 11;
                IF v_rest = 10 THEN
                    SET v_rest2 = fn_wsum(v_excl, 3,4,5,6,7,8,9, 0,0,0) % 11;
                    IF v_rest2 = 10 THEN SET v_chk = 0;
                    ELSE SET v_chk = v_rest2;
                    END IF;
                ELSE
                    SET v_chk = v_rest;
                END IF;
                IF v_chk = v_expected THEN SET p_result = 1; END IF;
            END IF;

        -- ── LT – modulus 11 with round-2, return_rest=True, 9 digits
        --        weights=[1,2,3,4,5,6,7,8]  round2=[3,4,5,6,7,8,9,1] ────────
        WHEN 'LT' THEN
            IF v_len = 9 AND v_before = '' AND v_after = '' THEN
                SET v_excl     = LEFT(v_number, 8);
                SET v_expected = CAST(SUBSTR(v_number, 9, 1) AS UNSIGNED);
                SET v_rest = fn_wsum(v_excl, 1,2,3,4,5,6,7,8, 0,0) % 11;
                IF v_rest = 10 THEN
                    SET v_rest2 = fn_wsum(v_excl, 3,4,5,6,7,8,9,1, 0,0) % 11;
                    IF v_rest2 = 10 THEN SET v_chk = 0;
                    ELSE SET v_chk = v_rest2;
                    END IF;
                ELSE
                    SET v_chk = v_rest;
                END IF;
                IF v_chk = v_expected THEN SET p_result = 1; END IF;
            END IF;

        -- ── BE – modulus 97, 10 digits ────────────────────────────────────────
        WHEN 'BE' THEN
            IF v_len = 10 AND v_before = '' AND v_after = '' THEN
                -- first 8 digits mod 97; 97 - remainder must equal last 2 digits
                IF (97 - (CAST(LEFT(v_number, 8) AS UNSIGNED) % 97))
                    = CAST(SUBSTR(v_number, 9, 2) AS UNSIGNED)
                THEN
                    SET p_result = 1;
                END IF;
            END IF;

        -- ── FR – SIREN (9 digits) or SIRET (14 digits), modulus 10 on first 9 ─
        WHEN 'FR' THEN
            IF v_before = '' AND (v_len = 9 OR v_len = 14) THEN
                SET v_excl     = LEFT(v_number, 8);
                SET v_expected = CAST(SUBSTR(v_number, 9, 1) AS UNSIGNED);
                IF fn_modulus10_calc(v_excl) = v_expected THEN SET p_result = 1; END IF;
            END IF;

        -- ── IT – Italy (similar to Luhn but 1-indexed parity) ────────────────
        -- 11-digit Partita IVA; even positions (1-based) from left get doubled
        WHEN 'IT' THEN
            BEGIN
                DECLARE v_i    INT DEFAULT 1;
                DECLARE v_x    INT;
                DECLARE v_res2 INT DEFAULT 0;
                -- Check for letter prefix (solopreneur) – just accept
                IF LEFT(v_s, 1) BETWEEN 'A' AND 'Z' AND LEFT(v_s, 2) != 'IT' THEN
                    SET p_result = 1;
                ELSEIF v_len = 11 AND v_before = '' AND v_after = '' THEN
                    SET v_excl     = LEFT(v_number, 10);
                    SET v_expected = CAST(SUBSTR(v_number, 11, 1) AS UNSIGNED);
                    WHILE v_i <= 10 DO
                        IF v_i % 2 = 0 THEN      -- even position (1-indexed)
                            SET v_x = CAST(SUBSTR(v_excl, v_i, 1) AS UNSIGNED) * 2;
                            IF v_x > 9 THEN SET v_x = v_x - 9; END IF;
                        ELSE
                            SET v_x = CAST(SUBSTR(v_excl, v_i, 1) AS UNSIGNED);
                        END IF;
                        SET v_res2 = v_res2 + v_x;
                        SET v_i = v_i + 1;
                    END WHILE;
                    IF (10 - (v_res2 % 10)) % 10 = v_expected THEN SET p_result = 1; END IF;
                END IF;
            END;

        -- ── HR – Croatia: OIB (11 digits, ISO7064) or MBS (9 digits, any) ────
        WHEN 'HR' THEN
            IF v_before = '' AND v_after = '' THEN
                IF v_len = 9 THEN
                    SET p_result = 1;   -- MBS: just 9 digits
                ELSEIF v_len = 11 THEN
                    SET v_excl     = LEFT(v_number, 10);
                    SET v_expected = CAST(SUBSTR(v_number, 11, 1) AS UNSIGNED);
                    IF fn_iso7064_calc(v_excl) = v_expected THEN SET p_result = 1; END IF;
                END IF;
            END IF;

        -- ── AT – Austria: [FB|FN|ZVR|…] + number + lowercase letter
        --        or ZVR-variant: ZVR/FNZVR prefix + 9-10 digits ───────────────
        WHEN 'AT' THEN
            BEGIN
                DECLARE v_bu VARCHAR(20);
                SET v_bu = UPPER(v_before);
                IF v_bu IN ('FNZVR','FNZVRZAHL','ZVR','ZVRZAHL') THEN
                    IF v_len BETWEEN 9 AND 10 THEN SET p_result = 1; END IF;
                ELSEIF v_bu IN ('FB','FN','') THEN
                    -- check char must be a lowercase letter (case-sensitive, like Python)
                    IF v_len BETWEEN 1 AND 6
                        AND CHAR_LENGTH(v_after) >= 1
                        AND ASCII(SUBSTR(v_after, 1, 1)) BETWEEN 97 AND 122
                    THEN
                        SET p_result = 1;
                    END IF;
                END IF;
            END;

        -- ── DE – Germany: [HRA|HRB|GnR|GsR|VR|PR] + 1-6 digits + court name
        --        Full XJustiz lookup omitted; validate prefix+length only ─────
        WHEN 'DE' THEN
            IF UPPER(v_before) IN ('HRA','HRB','GNR','GSR','VR','PR')
                AND v_len BETWEEN 1 AND 6
                AND CHAR_LENGTH(v_after) > 0
            THEN
                SET p_result = 1;
            END IF;

        -- ── GB – Great Britain ────────────────────────────────────────────────
        WHEN 'GB' THEN
            IF v_len = 8 AND v_before = '' AND v_after = '' THEN
                SET p_result = 1;
            ELSEIF v_len = 6 AND CHAR_LENGTH(v_before) = 2
                AND UPPER(v_before) IN ('SC','FC','BR','NI','OE','RC','OC','LP','SE','SO','SP','IP')
            THEN
                SET p_result = 1;
            ELSEIF v_len = 5
                AND UPPER(v_before) IN ('IP','SP')
                AND v_after = 'R'
            THEN
                SET p_result = 1;
            END IF;

        -- ── ES – Spain: [A-C,F,G,N,W] + 7 digits + letter  or 8 digits mod10 ─
        WHEN 'ES' THEN
            IF UPPER(v_before) IN ('A','B','C','F','G','N','W') THEN
                IF v_len = 7 AND CHAR_LENGTH(v_after) = 1 THEN
                    SET p_result = 1;
                ELSEIF v_len = 8 AND v_after = '' THEN
                    SET v_excl     = LEFT(v_number, 7);
                    SET v_expected = CAST(SUBSTR(v_number, 8, 1) AS UNSIGNED);
                    IF fn_modulus10_calc(v_excl) = v_expected THEN SET p_result = 1; END IF;
                END IF;
            END IF;

        -- ── CH – Switzerland: CHE-xxx.xxx.xxx (modulus 11) or CH + 11 digits ──
        WHEN 'CH' THEN
            IF UPPER(v_before) = 'CHE' AND v_len = 9 THEN
                SET v_excl     = LEFT(v_number, 8);
                SET v_expected = CAST(SUBSTR(v_number, 9, 1) AS UNSIGNED);
                SET v_rest = fn_wsum(v_excl, 5,4,3,2,7,6,5,4, 0,0) % 11;
                IF v_rest = 0 THEN SET v_chk = 0;
                ELSEIF v_rest = 1 THEN SET v_chk = 0;
                ELSE SET v_chk = 11 - v_rest;
                END IF;
                IF v_chk = v_expected THEN SET p_result = 1; END IF;
            ELSEIF UPPER(v_before) = 'CH' AND v_len = 11 THEN
                SET p_result = 1;
            END IF;

        -- ── MX – Mexico: 3 letters + YYMMDD + 3 chars = 12 total ─────────────
        WHEN 'MX' THEN
            BEGIN
                DECLARE v_yymmdd VARCHAR(6);
                DECLARE v_yyyy   VARCHAR(4);
                IF CHAR_LENGTH(v_s) = 12 THEN
                    SET v_yymmdd = SUBSTR(v_s, 4, 6);
                    IF v_yymmdd REGEXP '^[0-9]{6}$' THEN
                        SET v_yyyy = CONCAT('20', LEFT(v_yymmdd, 2));
                        -- Accept 2000-2099; simple date check
                        IF STR_TO_DATE(CONCAT(v_yyyy, SUBSTR(v_yymmdd,3,2), SUBSTR(v_yymmdd,5,2)), '%Y%m%d') IS NOT NULL THEN
                            SET p_result = 1;
                        END IF;
                    END IF;
                END IF;
            END;

        -- ── RO – Romania J-number (J<county>/<seq>/<YYYY>) ───────────────────
        WHEN 'RO' THEN
            BEGIN
                DECLARE v_parts  INT;
                DECLARE v_elem0  VARCHAR(50);
                DECLARE v_yyyy_r VARCHAR(4);
                -- After clean: J may survive since / is not removed
                -- Re-clean keeping /: undo slash removal? Actually fn_cid_clean doesn't touch /
                -- Use original p_ID with slashes
                SET v_parts = 1 + CHAR_LENGTH(p_ID) - CHAR_LENGTH(REPLACE(p_ID, '/', ''));
                IF v_parts >= 3 THEN
                    -- Extract year from last element after final /
                    SET v_yyyy_r = SUBSTR(p_ID, LOCATE('/', p_ID, LOCATE('/', p_ID, LOCATE('/', p_ID) + 1) + 1) + 1, 4);
                    IF v_yyyy_r REGEXP '^[0-9]{4}$'
                        AND CAST(v_yyyy_r AS UNSIGNED) BETWEEN 1800 AND 2099
                        AND LEFT(LTRIM(p_ID), 1) = 'J'
                    THEN
                        SET p_result = 1;
                    END IF;
                ELSEIF CHAR_LENGTH(p_ID) = 14 THEN
                    -- New compact format: J + YYYY + seq6 + county2 + chkdig
                    IF LEFT(p_ID, 1) = 'J'
                        AND SUBSTR(p_ID, 2, 4) REGEXP '^[0-9]{4}$'
                        AND CAST(SUBSTR(p_ID, 2, 4) AS UNSIGNED) BETWEEN 1800 AND 2099
                    THEN
                        SET p_result = 1;
                    END IF;
                END IF;
            END;

        -- ── Simple numeric countries (validate_just_numeric) ──────────────────

        -- CA: 9 digits
        WHEN 'CA' THEN
            IF v_len = 9 AND v_before = '' AND v_after = '' THEN SET p_result = 1; END IF;

        -- HU: 10 digits
        WHEN 'HU' THEN
            IF v_len = 10 AND v_before = '' AND v_after = '' THEN SET p_result = 1; END IF;

        -- IE: 3-6 digits
        WHEN 'IE' THEN
            IF v_len BETWEEN 3 AND 6 AND v_before = '' AND v_after = '' THEN SET p_result = 1; END IF;

        -- LI: FL + 11 digits
        WHEN 'LI' THEN
            IF v_len = 11 AND UPPER(v_before) = 'FL' AND v_after = '' THEN SET p_result = 1; END IF;

        -- LU: [B|F|G|J|''] + 1-6 digits (after_allowed=True: suffix like city name is OK)
        WHEN 'LU' THEN
            IF v_len BETWEEN 1 AND 6
                AND UPPER(v_before) IN ('B','F','G','J','')
            THEN SET p_result = 1; END IF;

        -- LV: 11 digits
        WHEN 'LV' THEN
            IF v_len = 11 AND v_before = '' AND v_after = '' THEN SET p_result = 1; END IF;

        -- MT: C + 3-5 digits
        WHEN 'MT' THEN
            IF v_len BETWEEN 3 AND 5 AND UPPER(v_before) = 'C' AND v_after = '' THEN SET p_result = 1; END IF;

        -- NL: 8 digits
        WHEN 'NL' THEN
            IF v_len = 8 AND v_before = '' AND v_after = '' THEN SET p_result = 1; END IF;

        -- PL: 10 digits
        WHEN 'PL' THEN
            IF v_len = 10 AND v_before = '' AND v_after = '' THEN SET p_result = 1; END IF;

        -- SI: 10 digits
        WHEN 'SI' THEN
            IF v_len = 10 AND v_before = '' AND v_after = '' THEN SET p_result = 1; END IF;

        -- SK: 8 digits
        WHEN 'SK' THEN
            IF v_len = 8 AND v_before = '' AND v_after = '' THEN SET p_result = 1; END IF;

        -- US: 9 digits (EIN)
        WHEN 'US' THEN
            IF v_len = 9 AND v_before = '' AND v_after = '' THEN SET p_result = 1; END IF;

        -- Unknown country → return 0 (already set)
        ELSE BEGIN END;

    END CASE;
END //

DELIMITER ;

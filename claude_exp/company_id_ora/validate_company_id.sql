-- validate_company_id.sql
-- Oracle PL/SQL package implementing company-ID validation.
-- Port of the MySQL validate_company_id.sql / snippets_copy/company_identifiers.py.
--
-- PREREQUISITE: xjustiz.sql must have been run and courts table loaded.
--
-- Note on Oracle vs MySQL empty-string handling:
--   Oracle treats '' as NULL; all "empty prefix/suffix" checks use IS NULL.
-- Note on package visibility:
--   Helper functions are declared PUBLIC (in spec) so VAT_ID_PKG can call them.

CREATE OR REPLACE PACKAGE COMPANY_ID_PKG AS

    FUNCTION fn_cid_clean(s IN VARCHAR2) RETURN VARCHAR2;
    FUNCTION fn_cid_before(s IN VARCHAR2) RETURN VARCHAR2;
    FUNCTION fn_cid_number(s IN VARCHAR2) RETURN VARCHAR2;
    FUNCTION fn_cid_after(s IN VARCHAR2) RETURN VARCHAR2;
    FUNCTION fn_modulus10_calc(s IN VARCHAR2) RETURN NUMBER;
    FUNCTION fn_wsum(
        s   IN VARCHAR2,
        w1  IN NUMBER, w2  IN NUMBER, w3  IN NUMBER, w4  IN NUMBER, w5  IN NUMBER,
        w6  IN NUMBER, w7  IN NUMBER, w8  IN NUMBER, w9  IN NUMBER, w10 IN NUMBER
    ) RETURN NUMBER;
    FUNCTION fn_iso7064_calc(s IN VARCHAR2) RETURN NUMBER;

    PROCEDURE validate_company_id(
        p_CNTRY  IN  VARCHAR2,
        p_ID     IN  VARCHAR2,
        p_result OUT NUMBER
    );

    PROCEDURE get_xjustiz_code(
        p_CNTRY IN  VARCHAR2,
        p_ID    IN  VARCHAR2,
        p_code  OUT VARCHAR2
    );

END COMPANY_ID_PKG;
/

CREATE OR REPLACE PACKAGE BODY COMPANY_ID_PKG AS

    -- Remove . - ( ) and spaces
    FUNCTION fn_cid_clean(s IN VARCHAR2) RETURN VARCHAR2 IS
    BEGIN
        RETURN REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(s, '.', ''), '-', ''), '(', ''), ')', ''), ' ', '');
    END fn_cid_clean;

    -- Extract leading non-digit prefix
    FUNCTION fn_cid_before(s IN VARCHAR2) RETURN VARCHAR2 IS
        i PLS_INTEGER := 1;
        n PLS_INTEGER := NVL(LENGTH(s), 0);
    BEGIN
        WHILE i <= n AND NOT (SUBSTR(s, i, 1) BETWEEN '0' AND '9') LOOP
            i := i + 1;
        END LOOP;
        RETURN SUBSTR(s, 1, i - 1);  -- NULL when i=1 (starts with digit)
    END fn_cid_before;

    -- Extract the run of digits in the middle
    FUNCTION fn_cid_number(s IN VARCHAR2) RETURN VARCHAR2 IS
        i PLS_INTEGER := 1;
        j PLS_INTEGER;
        n PLS_INTEGER := NVL(LENGTH(s), 0);
    BEGIN
        WHILE i <= n AND NOT (SUBSTR(s, i, 1) BETWEEN '0' AND '9') LOOP
            i := i + 1;
        END LOOP;
        j := i;
        WHILE j <= n AND (SUBSTR(s, j, 1) BETWEEN '0' AND '9') LOOP
            j := j + 1;
        END LOOP;
        RETURN SUBSTR(s, i, j - i);  -- NULL when no digits found
    END fn_cid_number;

    -- Extract trailing non-digit suffix after the digit block
    FUNCTION fn_cid_after(s IN VARCHAR2) RETURN VARCHAR2 IS
        i PLS_INTEGER := 1;
        n PLS_INTEGER := NVL(LENGTH(s), 0);
    BEGIN
        WHILE i <= n AND NOT (SUBSTR(s, i, 1) BETWEEN '0' AND '9') LOOP
            i := i + 1;
        END LOOP;
        WHILE i <= n AND (SUBSTR(s, i, 1) BETWEEN '0' AND '9') LOOP
            i := i + 1;
        END LOOP;
        RETURN SUBSTR(s, i);  -- NULL when nothing remains after digits
    END fn_cid_after;

    -- Luhn-style modulus-10 check digit.
    -- Input: all digits EXCEPT the check digit. Returns expected check digit (0-9).
    FUNCTION fn_modulus10_calc(s IN VARCHAR2) RETURN NUMBER IS
        res NUMBER      := 0;
        n   NUMBER;
        i   PLS_INTEGER := 1;
        len PLS_INTEGER := NVL(LENGTH(s), 0);
    BEGIN
        WHILE i <= len LOOP
            n := TO_NUMBER(SUBSTR(s, len - i + 1, 1));
            IF MOD(i - 1, 2) = 0 THEN
                n := n * 2;
                IF n > 9 THEN n := n - 9; END IF;
            END IF;
            res := res + n;
            i   := i + 1;
        END LOOP;
        res := 10 - MOD(res, 10);
        IF res = 10 THEN res := 0; END IF;
        RETURN res;
    END fn_modulus10_calc;

    -- Weighted sum for modulus-11 (up to 10 weights; pass 0 for unused slots).
    FUNCTION fn_wsum(
        s   IN VARCHAR2,
        w1  IN NUMBER, w2  IN NUMBER, w3  IN NUMBER, w4  IN NUMBER, w5  IN NUMBER,
        w6  IN NUMBER, w7  IN NUMBER, w8  IN NUMBER, w9  IN NUMBER, w10 IN NUMBER
    ) RETURN NUMBER IS
        i   PLS_INTEGER := 1;
        len PLS_INTEGER := NVL(LENGTH(s), 0);
        wi  NUMBER;
        res NUMBER      := 0;
    BEGIN
        WHILE i <= len LOOP
            CASE MOD(i - 1, 10)
                WHEN 0 THEN wi := w1;  WHEN 1 THEN wi := w2;  WHEN 2 THEN wi := w3;
                WHEN 3 THEN wi := w4;  WHEN 4 THEN wi := w5;  WHEN 5 THEN wi := w6;
                WHEN 6 THEN wi := w7;  WHEN 7 THEN wi := w8;  WHEN 8 THEN wi := w9;
                ELSE wi := w10;
            END CASE;
            res := res + TO_NUMBER(SUBSTR(s, i, 1)) * wi;
            i   := i + 1;
        END LOOP;
        RETURN res;
    END fn_wsum;

    -- ISO 7064 Mod-11/10 check digit (used for HR OIB, 11-digit number).
    -- Input: first 10 digits (excl check digit). Returns expected check digit.
    FUNCTION fn_iso7064_calc(s IN VARCHAR2) RETURN NUMBER IS
        i         PLS_INTEGER := 1;
        remainder NUMBER      := 10;
    BEGIN
        WHILE i <= 10 LOOP
            remainder := MOD(remainder + TO_NUMBER(SUBSTR(s, i, 1)), 10);
            IF remainder = 0 THEN remainder := 10; END IF;
            remainder := MOD(remainder * 2, 11);
            i         := i + 1;
        END LOOP;
        remainder := 11 - remainder;
        IF remainder = 10 THEN remainder := 0; END IF;
        RETURN remainder;
    END fn_iso7064_calc;


    PROCEDURE validate_company_id(
        p_CNTRY  IN  VARCHAR2,
        p_ID     IN  VARCHAR2,
        p_result OUT NUMBER
    ) IS
        v_s        VARCHAR2(200);
        v_before   VARCHAR2(50);
        v_number   VARCHAR2(50);
        v_after    VARCHAR2(50);
        v_excl     VARCHAR2(50);
        v_expected NUMBER;
        v_chk      NUMBER;
        v_len      PLS_INTEGER;
        v_rest     NUMBER;
        v_rest2    NUMBER;
        -- IT-specific
        v_i        PLS_INTEGER;
        v_x        NUMBER;
        v_res2     NUMBER;
        -- AT-specific
        v_bu       VARCHAR2(20);
        -- DE-specific
        v_xcode    VARCHAR2(10);
        -- MX-specific
        v_yymmdd   VARCHAR2(6);
        v_yyyy     VARCHAR2(4);
        v_date     DATE;
        -- RO-specific
        v_parts    NUMBER;
        v_yyyy_r   VARCHAR2(4);
        v_pos2     PLS_INTEGER;
        v_tmp      VARCHAR2(200);
        v_second   VARCHAR2(100);
        v_last     PLS_INTEGER;
    BEGIN
        p_result := 0;

        v_s      := fn_cid_clean(p_ID);
        v_before := fn_cid_before(v_s);
        v_number := fn_cid_number(v_s);
        v_after  := fn_cid_after(v_s);
        v_len    := NVL(LENGTH(v_number), 0);

        CASE p_CNTRY

            -- SE: modulus 10, exactly 10 digits, no prefix/suffix
            WHEN 'SE' THEN
                IF v_len = 10 AND v_before IS NULL AND v_after IS NULL THEN
                    v_excl     := SUBSTR(v_number, 1, 9);
                    v_expected := TO_NUMBER(SUBSTR(v_number, 10, 1));
                    IF fn_modulus10_calc(v_excl) = v_expected THEN p_result := 1; END IF;
                END IF;

            -- DK: modulus 11, weights [2,7,6,5,4,3,2,1], 8 digits
            WHEN 'DK' THEN
                IF v_len = 8 AND v_before IS NULL AND v_after IS NULL THEN
                    v_excl     := SUBSTR(v_number, 1, 7);
                    v_expected := TO_NUMBER(SUBSTR(v_number, 8, 1));
                    v_rest     := MOD(fn_wsum(v_excl, 2,7,6,5,4,3,2,0,0,0), 11);
                    IF    v_rest = 0 THEN v_chk := 0;
                    ELSIF v_rest = 1 THEN v_chk := 0;
                    ELSE                  v_chk := 11 - v_rest;
                    END IF;
                    IF v_chk = v_expected THEN p_result := 1; END IF;
                END IF;

            -- NO: modulus 11, weights [3,2,7,6,5,4,3,2,1], 9 digits
            WHEN 'NO' THEN
                IF v_len = 9 AND v_before IS NULL AND v_after IS NULL THEN
                    v_excl     := SUBSTR(v_number, 1, 8);
                    v_expected := TO_NUMBER(SUBSTR(v_number, 9, 1));
                    v_rest     := MOD(fn_wsum(v_excl, 3,2,7,6,5,4,3,2,0,0), 11);
                    IF    v_rest = 0 THEN v_chk := 0;
                    ELSIF v_rest = 1 THEN v_chk := 0;
                    ELSE                  v_chk := 11 - v_rest;
                    END IF;
                    IF v_chk = v_expected THEN p_result := 1; END IF;
                END IF;

            -- FI: modulus 11, weights [7,9,10,5,8,4,2,1], 8 digits, zero-padded
            WHEN 'FI' THEN
                IF v_before IS NULL AND v_after IS NULL AND v_len BETWEEN 1 AND 8 THEN
                    v_number   := LPAD(v_number, 8, '0');
                    v_len      := 8;
                    v_excl     := SUBSTR(v_number, 1, 7);
                    v_expected := TO_NUMBER(SUBSTR(v_number, 8, 1));
                    v_rest     := MOD(fn_wsum(v_excl, 7,9,10,5,8,4,2,0,0,0), 11);
                    IF    v_rest = 0 THEN v_chk := 0;
                    ELSIF v_rest = 1 THEN v_chk := 0;
                    ELSE                  v_chk := 11 - v_rest;
                    END IF;
                    IF v_chk = v_expected THEN p_result := 1; END IF;
                END IF;

            -- PT: modulus 11, weights [9,8,7,6,5,4,3,2], 9 digits
            WHEN 'PT' THEN
                IF v_len = 9 AND v_before IS NULL AND v_after IS NULL THEN
                    v_excl     := SUBSTR(v_number, 1, 8);
                    v_expected := TO_NUMBER(SUBSTR(v_number, 9, 1));
                    v_rest     := MOD(fn_wsum(v_excl, 9,8,7,6,5,4,3,2,0,0), 11);
                    IF    v_rest = 0 THEN v_chk := 0;
                    ELSIF v_rest = 1 THEN v_chk := 0;
                    ELSE                  v_chk := 11 - v_rest;
                    END IF;
                    IF v_chk = v_expected THEN p_result := 1; END IF;
                END IF;

            -- CZ: modulus 11, weights [8,7,6,5,4,3,2], 8 digits; rest=0 → chk=1
            WHEN 'CZ' THEN
                IF v_len = 8 AND v_before IS NULL AND v_after IS NULL THEN
                    v_excl     := SUBSTR(v_number, 1, 7);
                    v_expected := TO_NUMBER(SUBSTR(v_number, 8, 1));
                    v_rest     := MOD(fn_wsum(v_excl, 8,7,6,5,4,3,2,0,0,0), 11);
                    IF    v_rest = 0 THEN v_chk := 1;   -- special: 0→1
                    ELSIF v_rest = 1 THEN v_chk := 0;
                    ELSE                  v_chk := 11 - v_rest;
                    END IF;
                    IF v_chk = v_expected THEN p_result := 1; END IF;
                END IF;

            -- GR: modulus 11, weights [256,128,64,32,16,8,4,2], 9 digits; return_rest=True
            WHEN 'GR' THEN
                IF v_len = 9 AND v_before IS NULL AND v_after IS NULL THEN
                    v_excl     := SUBSTR(v_number, 1, 8);
                    v_expected := TO_NUMBER(SUBSTR(v_number, 9, 1));
                    v_rest     := MOD(fn_wsum(v_excl, 256,128,64,32,16,8,4,2,0,0), 11);
                    IF v_rest = 10 THEN v_chk := 0;
                    ELSE               v_chk := v_rest;
                    END IF;
                    IF v_chk = v_expected THEN p_result := 1; END IF;
                END IF;

            -- BG: modulus 11 with round-2 fallback, weights=[1..8], round2=[3..10], 9 digits
            WHEN 'BG' THEN
                IF v_len = 9 AND v_before IS NULL AND v_after IS NULL THEN
                    v_excl     := SUBSTR(v_number, 1, 8);
                    v_expected := TO_NUMBER(SUBSTR(v_number, 9, 1));
                    v_rest     := MOD(fn_wsum(v_excl, 1,2,3,4,5,6,7,8,0,0), 11);
                    IF v_rest = 10 THEN
                        v_rest2 := MOD(fn_wsum(v_excl, 3,4,5,6,7,8,9,10,0,0), 11);
                        IF v_rest2 = 10 THEN v_chk := 0;
                        ELSE                 v_chk := v_rest2;
                        END IF;
                    ELSE
                        v_chk := v_rest;
                    END IF;
                    IF v_chk = v_expected THEN p_result := 1; END IF;
                END IF;

            -- EE: modulus 11 with round-2, weights=[1..7], round2=[3..9], 8 digits
            WHEN 'EE' THEN
                IF v_len = 8 AND v_before IS NULL AND v_after IS NULL THEN
                    v_excl     := SUBSTR(v_number, 1, 7);
                    v_expected := TO_NUMBER(SUBSTR(v_number, 8, 1));
                    v_rest     := MOD(fn_wsum(v_excl, 1,2,3,4,5,6,7,0,0,0), 11);
                    IF v_rest = 10 THEN
                        v_rest2 := MOD(fn_wsum(v_excl, 3,4,5,6,7,8,9,0,0,0), 11);
                        IF v_rest2 = 10 THEN v_chk := 0;
                        ELSE                 v_chk := v_rest2;
                        END IF;
                    ELSE
                        v_chk := v_rest;
                    END IF;
                    IF v_chk = v_expected THEN p_result := 1; END IF;
                END IF;

            -- LT: modulus 11 with round-2, weights=[1..8], round2=[3..9,1], 9 digits
            WHEN 'LT' THEN
                IF v_len = 9 AND v_before IS NULL AND v_after IS NULL THEN
                    v_excl     := SUBSTR(v_number, 1, 8);
                    v_expected := TO_NUMBER(SUBSTR(v_number, 9, 1));
                    v_rest     := MOD(fn_wsum(v_excl, 1,2,3,4,5,6,7,8,0,0), 11);
                    IF v_rest = 10 THEN
                        v_rest2 := MOD(fn_wsum(v_excl, 3,4,5,6,7,8,9,1,0,0), 11);
                        IF v_rest2 = 10 THEN v_chk := 0;
                        ELSE                 v_chk := v_rest2;
                        END IF;
                    ELSE
                        v_chk := v_rest;
                    END IF;
                    IF v_chk = v_expected THEN p_result := 1; END IF;
                END IF;

            -- BE: modulus 97, 10 digits; 97 - (first8 % 97) = last2
            WHEN 'BE' THEN
                IF v_len = 10 AND v_before IS NULL AND v_after IS NULL THEN
                    IF (97 - MOD(TO_NUMBER(SUBSTR(v_number, 1, 8)), 97))
                        = TO_NUMBER(SUBSTR(v_number, 9, 2))
                    THEN
                        p_result := 1;
                    END IF;
                END IF;

            -- FR: SIREN (9 digits) or SIRET (14 digits), modulus 10 on first 9
            WHEN 'FR' THEN
                IF v_before IS NULL AND (v_len = 9 OR v_len = 14) THEN
                    v_excl     := SUBSTR(v_number, 1, 8);
                    v_expected := TO_NUMBER(SUBSTR(v_number, 9, 1));
                    IF fn_modulus10_calc(v_excl) = v_expected THEN p_result := 1; END IF;
                END IF;

            -- IT: 11-digit Partita IVA (Luhn-style, 1-indexed parity) or letter prefix
            WHEN 'IT' THEN
                IF SUBSTR(v_s, 1, 1) BETWEEN 'A' AND 'Z' AND SUBSTR(v_s, 1, 2) != 'IT' THEN
                    p_result := 1;  -- solopreneur letter prefix
                ELSIF v_len = 11 AND v_before IS NULL AND v_after IS NULL THEN
                    v_excl     := SUBSTR(v_number, 1, 10);
                    v_expected := TO_NUMBER(SUBSTR(v_number, 11, 1));
                    v_i        := 1;
                    v_res2     := 0;
                    WHILE v_i <= 10 LOOP
                        IF MOD(v_i, 2) = 0 THEN
                            v_x := TO_NUMBER(SUBSTR(v_excl, v_i, 1)) * 2;
                            IF v_x > 9 THEN v_x := v_x - 9; END IF;
                        ELSE
                            v_x := TO_NUMBER(SUBSTR(v_excl, v_i, 1));
                        END IF;
                        v_res2 := v_res2 + v_x;
                        v_i    := v_i + 1;
                    END LOOP;
                    IF MOD(10 - MOD(v_res2, 10), 10) = v_expected THEN p_result := 1; END IF;
                END IF;

            -- HR: OIB (11 digits, ISO7064) or MBS (9 digits, any)
            WHEN 'HR' THEN
                IF v_before IS NULL AND v_after IS NULL THEN
                    IF v_len = 9 THEN
                        p_result := 1;
                    ELSIF v_len = 11 THEN
                        v_excl     := SUBSTR(v_number, 1, 10);
                        v_expected := TO_NUMBER(SUBSTR(v_number, 11, 1));
                        IF fn_iso7064_calc(v_excl) = v_expected THEN p_result := 1; END IF;
                    END IF;
                END IF;

            -- AT: ZVR/FNZVR variants, or FB/FN/bare prefix + 1-6 digits + lowercase letter
            WHEN 'AT' THEN
                v_bu := UPPER(v_before);
                IF v_bu IN ('FNZVR','FNZVRZAHL','ZVR','ZVRZAHL') THEN
                    IF v_len BETWEEN 9 AND 10 THEN p_result := 1; END IF;
                ELSIF v_bu IS NULL OR v_bu IN ('FB','FN') THEN
                    IF v_len BETWEEN 1 AND 6
                        AND v_after IS NOT NULL
                        AND ASCII(SUBSTR(v_after, 1, 1)) BETWEEN 97 AND 122
                    THEN
                        p_result := 1;
                    END IF;
                END IF;

            -- DE: [HRA|HRB|GNR|GSR|VR|PR] + 1-6 digits + court name in XJustiz
            WHEN 'DE' THEN
                v_xcode := NULL;
                IF UPPER(v_before) IN ('HRA','HRB','GNR','GSR','VR','PR')
                    AND v_len BETWEEN 1 AND 6
                    AND v_after IS NOT NULL
                THEN
                    BEGIN
                        SELECT court_code INTO v_xcode FROM courts WHERE court_key = v_after;
                    EXCEPTION
                        WHEN NO_DATA_FOUND THEN v_xcode := NULL;
                    END;
                    IF v_xcode IS NOT NULL THEN p_result := 1; END IF;
                END IF;

            -- GB: 8 digits, or 2-letter prefix + 6 digits, or IP/SP + 5 digits + R
            WHEN 'GB' THEN
                IF v_len = 8 AND v_before IS NULL AND v_after IS NULL THEN
                    p_result := 1;
                ELSIF v_len = 6
                    AND LENGTH(v_before) = 2
                    AND UPPER(v_before) IN ('SC','FC','BR','NI','OE','RC','OC','LP','SE','SO','SP','IP')
                THEN
                    p_result := 1;
                ELSIF v_len = 5
                    AND UPPER(v_before) IN ('IP','SP')
                    AND v_after = 'R'
                THEN
                    p_result := 1;
                END IF;

            -- ES: [A-C,F,G,N,W] + 7 digits + letter, or 8 digits modulus 10
            WHEN 'ES' THEN
                IF UPPER(v_before) IN ('A','B','C','F','G','N','W') THEN
                    IF v_len = 7 AND LENGTH(v_after) = 1 THEN
                        p_result := 1;
                    ELSIF v_len = 8 AND v_after IS NULL THEN
                        v_excl     := SUBSTR(v_number, 1, 7);
                        v_expected := TO_NUMBER(SUBSTR(v_number, 8, 1));
                        IF fn_modulus10_calc(v_excl) = v_expected THEN p_result := 1; END IF;
                    END IF;
                END IF;

            -- CH: CHE + 9 digits (modulus 11) or CH + 11 digits (any)
            WHEN 'CH' THEN
                IF UPPER(v_before) = 'CHE' AND v_len = 9 THEN
                    v_excl     := SUBSTR(v_number, 1, 8);
                    v_expected := TO_NUMBER(SUBSTR(v_number, 9, 1));
                    v_rest     := MOD(fn_wsum(v_excl, 5,4,3,2,7,6,5,4,0,0), 11);
                    IF    v_rest = 0 THEN v_chk := 0;
                    ELSIF v_rest = 1 THEN v_chk := 0;
                    ELSE                  v_chk := 11 - v_rest;
                    END IF;
                    IF v_chk = v_expected THEN p_result := 1; END IF;
                ELSIF UPPER(v_before) = 'CH' AND v_len = 11 THEN
                    p_result := 1;
                END IF;

            -- MX: 3 letters + YYMMDD + 3 chars = 12 total; date must be valid 2000-2099
            WHEN 'MX' THEN
                IF NVL(LENGTH(v_s), 0) = 12 THEN
                    v_yymmdd := SUBSTR(v_s, 4, 6);
                    IF REGEXP_LIKE(v_yymmdd, '^[0-9]{6}$') THEN
                        v_yyyy := '20' || SUBSTR(v_yymmdd, 1, 2);
                        BEGIN
                            v_date   := TO_DATE(v_yyyy || SUBSTR(v_yymmdd, 3, 2) || SUBSTR(v_yymmdd, 5, 2), 'YYYYMMDD');
                            p_result := 1;
                        EXCEPTION
                            WHEN OTHERS THEN NULL;
                        END;
                    END IF;
                END IF;

            -- RO: J-number with slash variants or compact 14-char format
            WHEN 'RO' THEN
                v_parts := 1 + NVL(LENGTH(p_ID), 0) - NVL(LENGTH(REPLACE(p_ID, '/', '')), 0);
                IF v_parts >= 3 THEN
                    -- Year is always after the last '/'
                    v_last   := INSTR(p_ID, '/', -1);
                    v_yyyy_r := SUBSTR(p_ID, v_last + 1, 4);
                    IF REGEXP_LIKE(v_yyyy_r, '^[0-9]{4}$')
                        AND TO_NUMBER(v_yyyy_r) BETWEEN 1800 AND 2099
                    THEN
                        IF v_parts = 5 THEN
                            -- /J/county/seq/YYYY: 2nd element (between 1st and 2nd '/') must be 'J'
                            v_pos2   := INSTR(p_ID, '/', 1, 2);
                            v_tmp    := SUBSTR(p_ID, 1, v_pos2 - 1);
                            v_second := SUBSTR(v_tmp, INSTR(v_tmp, '/', -1) + 1);
                            IF v_second = 'J' THEN p_result := 1; END IF;
                        ELSIF SUBSTR(p_ID, 1, 1) = 'J' THEN
                            p_result := 1;
                        END IF;
                    END IF;
                ELSIF NVL(LENGTH(p_ID), 0) = 14 THEN
                    -- Compact: J + YYYY + seq6 + county2 + chkdig
                    IF SUBSTR(p_ID, 1, 1) = 'J'
                        AND REGEXP_LIKE(SUBSTR(p_ID, 2, 4), '^[0-9]{4}$')
                        AND TO_NUMBER(SUBSTR(p_ID, 2, 4)) BETWEEN 1800 AND 2099
                    THEN
                        p_result := 1;
                    END IF;
                END IF;

            -- Simple numeric-only countries
            WHEN 'CA' THEN
                IF v_len = 9  AND v_before IS NULL AND v_after IS NULL THEN p_result := 1; END IF;
            WHEN 'HU' THEN
                IF v_len = 10 AND v_before IS NULL AND v_after IS NULL THEN p_result := 1; END IF;
            WHEN 'IE' THEN
                IF v_len BETWEEN 3 AND 6 AND v_before IS NULL AND v_after IS NULL THEN p_result := 1; END IF;
            WHEN 'LI' THEN
                IF v_len = 11 AND UPPER(v_before) = 'FL' AND v_after IS NULL THEN p_result := 1; END IF;
            WHEN 'LU' THEN
                -- Optional prefix B/F/G/J or none; suffix allowed (city name)
                IF v_len BETWEEN 1 AND 6
                    AND (v_before IS NULL OR UPPER(v_before) IN ('B','F','G','J'))
                THEN p_result := 1; END IF;
            WHEN 'LV' THEN
                IF v_len = 11 AND v_before IS NULL AND v_after IS NULL THEN p_result := 1; END IF;
            WHEN 'MT' THEN
                IF v_len BETWEEN 3 AND 6 AND UPPER(v_before) IN ('C','OC') AND v_after IS NULL THEN p_result := 1; END IF;
            WHEN 'NL' THEN
                IF v_len = 8  AND v_before IS NULL AND v_after IS NULL THEN p_result := 1; END IF;
            WHEN 'PL' THEN
                IF v_len = 10 AND v_before IS NULL AND v_after IS NULL THEN p_result := 1; END IF;
            WHEN 'SI' THEN
                IF v_len = 10 AND v_before IS NULL AND v_after IS NULL THEN p_result := 1; END IF;
            WHEN 'SK' THEN
                IF v_len = 8  AND v_before IS NULL AND v_after IS NULL THEN p_result := 1; END IF;
            WHEN 'US' THEN
                IF v_len = 9  AND v_before IS NULL AND v_after IS NULL THEN p_result := 1; END IF;
            -- IM: exactly 6 digits, no prefix, suffix allowed
            WHEN 'IM' THEN
                IF v_len = 6 AND v_before IS NULL THEN p_result := 1; END IF;
            -- JE: 4-7 digits, no prefix, no suffix
            WHEN 'JE' THEN
                IF v_len BETWEEN 4 AND 7 AND v_before IS NULL AND v_after IS NULL THEN p_result := 1; END IF;
            -- GY: 1-6 digits, no prefix, no suffix
            WHEN 'GY' THEN
                IF v_len BETWEEN 1 AND 6 AND v_before IS NULL AND v_after IS NULL THEN p_result := 1; END IF;

            ELSE NULL;  -- unknown country → return 0

        END CASE;

    EXCEPTION
        WHEN OTHERS THEN p_result := 0;
    END validate_company_id;


    -- For a DE company ID, returns the XJustiz court_code embedded in the ID.
    -- Returns '' when CNTRY != 'DE' or court name not found.
    PROCEDURE get_xjustiz_code(
        p_CNTRY IN  VARCHAR2,
        p_ID    IN  VARCHAR2,
        p_code  OUT VARCHAR2
    ) IS
        v_after VARCHAR2(50);
    BEGIN
        p_code := '';
        IF p_CNTRY = 'DE' THEN
            v_after := fn_cid_after(fn_cid_clean(p_ID));
            IF v_after IS NOT NULL THEN
                BEGIN
                    SELECT NVL(court_code, '') INTO p_code FROM courts WHERE court_key = v_after;
                EXCEPTION
                    WHEN NO_DATA_FOUND THEN p_code := '';
                END;
            END IF;
        END IF;
    END get_xjustiz_code;

END COMPANY_ID_PKG;
/

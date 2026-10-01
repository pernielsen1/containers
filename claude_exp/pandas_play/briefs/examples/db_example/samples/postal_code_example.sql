-- AnaCredit postal code UDFs (anacredit_postal_code.py, postal_code_formats.csv).
--   anacredit_postal_valid(zip, country)     1 / 0   (1 too if the country has no rule)
--   anacredit_postal_verbosed(zip, country)  noise removed, separator restored; NULL if unfixable
--
-- Run (from db_example/):
--   python3 run_sql.py samples/postal_code_example.sql --env test --db postal_demo
--
-- Sweden:  3 digits, blank, 2 digits          12345  -> 123 45
-- Germany: 5 digits, no blank                 123 45 -> 12345
-- Poland:  2 digits, '-', 3 digits            12345  -> 12-345
-- Great Britain (GB - "UK" is not an ISO code): the handbook section 4.5 has NO rule for
--   it, so every code is "valid" and verbosed only trims -- the postal code is checked
--   for presence only (CY0100), never for format.

DROP TABLE IF EXISTS postal_demo;
CREATE TABLE postal_demo (country TEXT, postal_code TEXT);
INSERT INTO postal_demo VALUES
    ('SE', '123 45'),      -- valid
    ('SE', '12345'),       -- blank missing
    ('SE', '123-45'),      -- wrong separator
    ('SE', '023 45'),      -- first digit may not be 0, cannot be fixed
    ('DE', '12345'),       -- valid
    ('DE', '123 45'),      -- blank not allowed
    ('DE', '1234'),        -- too short, cannot be fixed
    ('PL', '12-345'),      -- valid
    ('PL', '12345'),       -- dash missing
    ('PL', '12 345'),      -- wrong separator
    ('GB', 'SW1A 1AA'),    -- no rule: valid
    ('GB', 'sw1a1aa'),     -- no rule: "valid", verbosed does NOT reformat
    ('GB', 'not a code'),  -- no rule: still "valid"
    ('UK', 'SW1A 1AA');    -- "UK" is not ISO (GB is), also no rule

SELECT country,
       postal_code,
       anacredit_postal_valid(postal_code, country)    AS valid,
       anacredit_postal_verbosed(postal_code, country) AS verbosed
FROM postal_demo;

PRAGMA export = 'postal_code_example_export.csv';
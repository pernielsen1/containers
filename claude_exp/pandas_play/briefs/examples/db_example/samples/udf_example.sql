-- example for run_sql.py: my_upper is always available (udf_definitions.csv);
-- validate_COMPANY_ID comes from this script's own udf_extra.csv (relative
-- to this script). Plain sqlite3 ignores the unknown pragma.
PRAGMA udf_extra = 'udf_extra.csv';

SELECT my_upper('acme a/s')                                          AS name_upper,
       validate_COMPANY_ID('12345674', 'DK')                         AS result_json,
       json_extract(validate_COMPANY_ID('12345674', 'DK'), '$.validation_result') AS is_valid;

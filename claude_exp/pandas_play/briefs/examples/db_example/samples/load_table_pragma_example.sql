-- run against a fresh db, e.g.:
--   python3 ../run_sql.py load_table_pragma_example.sql --db load_table_demo --config config.json
--
-- table_1.csv sits right next to this script -- infile is resolved
-- relative to the file the PRAGMA is written in, same as
-- PRAGMA include and udf_extra.
PRAGMA load_table = 'table_1.csv table_1';

SELECT * FROM table_1;

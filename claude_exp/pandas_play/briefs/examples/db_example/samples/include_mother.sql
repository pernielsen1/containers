-- mother script: reuses include_formatting.sql's view, decides its own
-- filter and its own PRAGMA export -- run against a db that already has
-- table_1 loaded, e.g.:
--   python3 ../load_table.py table_1.csv include_demo table_1 --config config.json
--   python3 ../run_sql.py include_mother.sql --db include_demo --config config.json
PRAGMA include = 'include_formatting.sql';

SELECT * FROM my_view WHERE a_number > 15;
PRAGMA export = 'include_mother_out.csv';

-- run against a fresh db, e.g.:
--   python3 ../run_sql.py default_field_and_print_example.sql --db defaults_demo --config config.json
--
-- my_key gets typed as int with no row for THIS table in
-- field_definitions.csv -- it's picked up from the default (blank
-- table) row for my_key that already lives there.
PRAGMA load_table = 'my_key_example.csv my_key_table';

PRAGMA print = 'my_key_table loaded -- my_key came from the default row, typed as int';

SELECT my_key, typeof(my_key) AS sqlite_type FROM my_key_table;

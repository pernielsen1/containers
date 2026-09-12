-- example multi-statement script for run_sql.py: a non-SELECT
-- statement followed by the SELECT whose result set gets exported.
UPDATE table_2 SET desc = desc || '!' WHERE key2 = 'K1';

SELECT t1.key AS key1, t1.desc, t1.a_number, t2.a_float, t2.a_date, t2.another_field
FROM table_1 t1
JOIN table_2 t2 ON t1.key = t2.key2;

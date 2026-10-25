PRAGMA print = 'hello from sql_ui';
CREATE TABLE IF NOT EXISTS demo (id INTEGER, name TEXT);
DELETE FROM demo;
INSERT INTO demo VALUES (1, 'alpha'), (2, 'beta'), (3, 'gamma');
SELECT id, upper(name) AS name_upper FROM demo ORDER BY id;
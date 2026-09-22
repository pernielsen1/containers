-- shared formatting step: no PRAGMA export of its own -- the mother
-- script that includes this one controls when/whether to export.
CREATE VIEW IF NOT EXISTS my_view AS
SELECT key, my_upper(desc) AS desc_upper, a_number
FROM table_1;

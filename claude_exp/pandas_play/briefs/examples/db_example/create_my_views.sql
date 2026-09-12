DROP VIEW IF EXISTS my_view;
CREATE VIEW IF NOT EXISTS my_view as 
SELECT a.a_key, a.name, a.c_key, 
   c.name as c_name, c.d_key, 
   d.name as d_name 

FROM a_cust a 
    left join c_cust c on a.c_key  = c.c_key
    left join d_cust d on c.d_key = d.d_key
WHERE 
    a_key < 'A999'
;
select * from my_view;
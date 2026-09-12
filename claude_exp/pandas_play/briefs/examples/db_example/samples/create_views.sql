create VIEW IF NOT EXISTS my_view as 
select * from table_1 a inner join table_2 b on a.key  = b.key2
;
select * from my_view;
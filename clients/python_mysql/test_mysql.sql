create database test_db;
create table test_db.today (account varchar(20), amount decimal(11, 2), currency char(3));
insert into test_db.today VALUES('acc1', '42.43', 'SEK');
commit;

select * from test_db.today;
insert into test_db.today VALUES('acc1', '-142.43', 'SEK');
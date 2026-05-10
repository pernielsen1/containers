# copy company_id_sql
## mysql version of company_id sql
before coding make a plan and feel free to ask questions.
in ../company_id_sql is a mysql version of validating company ids
contains a number of sql scripts implementing validation of company_id, vat_id and a special case for xjustis in Germany.
there is also a test case file company_ids.csv 
and a validation script test_company_id.py 
in this directory I need an oracle implementation connecting to our oracle container

## changes
in ../company_id_sql/snippets_copy is the original inspiration to the stored procedures. 
in ../../snippets is the current version. 
There are minor changes to the company_identifiers.py file which should be reflected in the stored procedures.
this is also reflected in the ../../snippets/tests/test_company_identifiers.py which have a number of new cases not found in the test_company_id.py
 

 
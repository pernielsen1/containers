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

# multi db oracle and mysql
## two compose two sets of sql implementation
I need the implementation to work with both oracle and mysql.
the compose builds a oracle container
make one which implements a mysql container.
and init_script let's me choose which database to use setting environment variables for compose file etc. 
script up - starts the container,  script down shuts it down
script test runs the test_company_id.py with the selected database.
the user-id and password uses existing environment variables for both databases


 
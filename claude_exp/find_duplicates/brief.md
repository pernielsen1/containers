do not code just yet but make a plan for some new scripts
assume that pandas is available in the environment

1:Init:
first a init_counterparties.py script creating a csv counterparties based on test_counterparties.csv
selecting only the unique ie. if a counterparty has potential duplicate select only the first.
reuse logic from find_duplicates.py

2: Next: 
create a new version reusing the logic for identifying possible duplicates before loading to counterparties.csv
the script load_new_counterparties.py should read a file new_counterparties.csv and 
create two files -  OK_new_counterparties and possible_errors.csv

possible_errors.csv should have one row per identified possible duplicate i.e. if n possible duplicates found 
in counterparties then there should be n rows in possible_errors.csv
possible_errors.csv should have the columns from both new_counterparties.csv and counterparties.csv. 
The columns should be listed next to each other i.e. NM_CP from new counter_parties.csv should be followed by NM_CP from existing counterparties column name with a prefix of exist i.e. exist_NM_CP as example.


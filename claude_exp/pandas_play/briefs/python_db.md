# pandas & csv 
pandas is a well functioning tool but not a database
I have observed that I store data in csv files - even large amounts.  a kind of csv database
other observations is the understanding of data I often fall to take all as str and then selected fields 
as numeric/dates - and fall into the "na" trap
Often when falling into the csv-db pattern I'm in a environment where I can't just throw in an install of a db
suggestions - or is the csv-db pattern the best option

## pandas & csv -> sqllite examples
let's assume we have a csv with fields:
key (a string), num_value (an integer), decimal_value (a float), the_date (a date), the_time_stamp (a timestamp)
a_value(a simple string)
all may be empty - i.e. pandas would throw them into nan
the majority of the fields should be treated as str--- i only those who needs intepretating should be named

I need to see examples in python 
creating tables and loading values
also include examples with more than one table in one database..
i somehow need to see code to get more in the understanding of things


# let us look at synchronizing 
let's chat about the following
let's chat about the following
we have sorted out the sqlite db cannot be on a synched onedrive. 
so make a setup where we have a config.json pointing the db_storage into a subdirectory of my temp directory.
maka a script  - sync.sh which basically copies the db tables to a location within my onedrive directory structure
let this name also be found in the repo's config.json
come up with good naming strategy 

# more advice on sqllite 
good choice and think I have a way forward will be moving forward with that will the command line client also be included in the standard windows python distribution ?

# python -m sqllite seems the way to go make it easy for me 
make a .sh script creating an example db and then opening the client with this database

# make load_csv.py more generic 
ask question if unclear
make a csv called field_definitions.csv with three fields
table, field and type. 
load_csv.py should now take three arguments 
infile db table
the infile is the csv to be loaded
db is the name of the database to be stored in db_storage_dir
infile is the csv to be read
table is the table to be created and loaded with values. if the table exist from before - drop it first.
when reading the csv assume all columns are str, except if the table=parameter and field=column can be found in field_definitions.csv in that case the type has the overloading type in pandas lingo i.e. float, integer etc.
the table to be created should have all the columns that are in the csv 
make an example where we have two csvs to load (small) 
table_1 has three fields key, desc, a_number -  a_number should be in the field_definitions.csv with type float
table_2 has three fields key2, desc, a_float, a_date -  a_float should be the field_definitions.csv with type int and a_date 

key, key2 and desc should not be in field_definitions since they go to the default str


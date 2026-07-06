# convert a multi sheet xlsb to one basic csv file per key field
## first creata a plan for 
create a class which accepts an input file name and a area_field_name as init parameter
a suitable test file can be found by reading go-xlsb.py variable IN_FILe
the file is an xlsb file - pandas support is enabled in the environment and the pandas is available in the environment.
create a process looping through all sheets - OBS THIS MAY BE A LARGE FILE
and then create one csv file in folder output per area_field_name
in the example file it will be the column called 'area'
the values in one sheet may be in the same area as the next sheet.
the solution needs to be able to handle files of let's say 30 million rows in total divided by excel only allowing one million per sheet
## after plan - let's discuss and then implement

## minor tweak to 0_xlsb_to_csv.py
the output csv should not have ACPT or PROD in their filenames but rather be moved into the folders ACPT or PROD
Then we will end up having the same file names in ACPT and PROD which will serve as input for the next process - the compare
## the compare
produce plan for building a pything file 1_compare.py which will read all files from 
output/compare/ACPT and for each file find a file with the same name in output/compare/PROD
the file pair should then be read into pandas dataframes and the dataframes compared with respect to the key fields.
for each filename the keyfields should be defined in an external json struct stored in keyfields.json.
those records which are in both ACPT and PROD should be written as csv  to output/BOTH
those which are only in the ACPT should be written to output/ONLY_ACPT
those which are onlyn in the PROD should be written to output/ONLY_PROD


## update to compare 
as usual give me a plan before building .. I have some changes
the keyfield.json is now named schema.json
the original key fields are now found per file in subpath keys 
there is also a subpath which is a list of columns to ignore.
all fields not in keys or ignore are attributes.
so if we have situation where keys are in both ACPT and PROD but if attributes are change these should be stored in output directory output/BOTH_cHANGED.
in this output we should see first all keys and then the ACPT and PROD values paired in the output CSV

## moving on to a different kind of input
plan before build
we need a new 0_xlsb_multi_sto_csv.py
it shoud read input from same ONE_DRIVE as found in 0_xlsb_to_csv.py
but input directory should be found in test_xlsb/test_multi_sheet
the excel files here has one sheet per area there are also sheets which should not be loaded.
the json multi_sheets.json has the sheet names to be loaded as key and the area name as attribue. after loading the excel a CSV file should be created in similar pattern as from 0_xlsb_to_csv.py to same output directory i.e. will also be input to next session for comparing the ACPT and PROD environment.

## optimizing a bit 
add a config.json where the ONE_DRIVE are stored and 
the relative input paths for both 0_xlsb_multi_sto_csv and 0_xlsb_to_csv are stored

## and making sure of csv permanent csv skill
when writing csv files it is important that they are also readable in Excel with
special characters thing I'm in scandinava meaning ä, å and even in germany with ü and funny double ss-es like ß (sharfes s)
let's discuss adjust and make sure this is a global preference

## corrective input to 0_xlsb_to_csv.py
only accept sheet names starting with 'v' (lowercase)read ope
in the output only have columns named in key_columns or value_columns
I have run the utility on production data and sometimes the check_no_upcast creates problems which is really not needed.
treat all values read as strings - the main purpose of this exercise is to compare two datasets - not calculating on them

## optimize performance
ran the utity against large data set (13 million rows) all in all.
observed the following
1: handling in chunks - fine - but input data may be unordered - probably an idea to sort a chunk before ejecting to csv's
2: progress - bar 
write a dot on same line for each chunk (50000) write a number for each million produced and make newline for a milliom

## optimize two
the current version will expect to have a acpt and prod file.
implement a commmand line parameter can be 
acpt (only load acpt)
prod (only load prod)
both (the default - i.e. as it works today expect and load both)
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

Do not code just yet but make a plan for some new scripts
restrictions:
there are no restrictions on what is available in the environment but use pandas where appropriate.
all new packages which should be needed would need an assement - make a plan for packages to install
and be able to describe them in an install.sh script - then I will manually install them before we go into coding mode.

objective:
There is a csv file called master.csv containg corporate entities it has the following fields
id: always filled an internal "unique key" for the counterparty
name:  official name of the entity
address: address of the entity
postal_code: the postal code for the entity
city: the city 
country: the country
corporate_identifer:  may or may not exist if it does it is the commercial register identifier i.e. in Sweden the organisation number, in denmark the CVR-number, in germany the HRB(HRA etc), in austria Firmenbuch number / ZVR zahl etc... the corporate identifier is a strong identifier - but some countries have "loose formatting" - Germany being the worst.. the entities we are interested in will be in Europe, US, Canada & Mexico.

Objective:
we have a new file candidates.csv containing the same fields as master.csv.
the file should be sorted in three:
add.csv :  the entries which could be added to master.csv without introducing new duplicates
duplicates.csv: when the entry in candidates.csv seems to be a duplicate in master.csv. duplicates.csv should contain both the data from the candidates.csv plus the data from master.csv which is seens as a possible duplicate - exemption is if candidates.csv's id already in master.csv.  Then it is an existing entry and that duplicate match can be ignored - but it could find other duplicates in master.csv

There will be no test data - expect you can make it up your self.

let's create a plan and feel free to ask questions.

added 1:
I know we have run a similar task with find_duplicates - but try to thing out of the box. it was just one way of solving the problem. Feel free to propose others and do not thing of reusing the codebase 

added 2:
Good explanations :-)
I will be continuously cleaning the data and have a "zero tolerance" in the end so I would like to have both approaches possible too use.
Realise that I need an easy way to give as input -  ignore these duplicates - i.e. a file ignore.csv containig id combinations to ignore - since they are not duplicates

added 3:
create a test file for candidates.csv

added 4:
create a directory regression with a script test.sh - which I can use if I manually (ooohhh it might happen) changes the python code and want to validate that these tests still works.


create a python application fetch_duns_info.py 
reading duns_to_collect.csv and for each record 
does a search using the DUNS_NO in the api defined in api-docs.json
credentials ClientId and ClientSecret are defined in the config.json file.
The retrieved information should be written to a file stored in the output folder with a name built up of the 
DUNS_NO followed by '_' and a timestamp followed by '.txt'

requesting data from external api bears a cost so we need a cache function.
this should be implemented in a seperate class "duns_cache".
before calling the api for retrieving information it should first be checked if data is available in cache and "fresh enough". i.e. implement a function which is get_data(row) where the row is the pandas row originating from duns_to_collect.csv
if the row has a DUNS_NO which can be found in the cache directory (first part of the file name)
the directory cache has the files already retrieved via the api. 
The naming convention means that the DUNS_No and timestame is available.
the config json should have a new parameter "age_in_days" representing the days allowed for a cache to age i.e. if the file found in directory cache is not older the "age_in_days" then don't collect new information¨

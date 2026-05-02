make a plan before coding

Prereq:
we have a directory input containing files with the pattern:
key_type_xxxx.json
where xxxx could be anything like a timestamp or whatever.
The directory contains a large number of files.

Objective: 
End of with a csv file with key, type, base64_json
the base_64 json is the zipped version of the contents of the files.
the json structure should be validated before stored in base64_sjon in the csv.
files not validating should end up in directory error - if naming conflict add a unique id

Test data: 
expect you make it your self - plus a test suite.

Resilience:
The resulting csv file will be gigantic - important that adding new entries does not corrupt the end reuslt.
when a file is finally committed to the resulting csv file it should be in directory committed.

test info:
The "large file" should not be tested with actual large files - just simulate it


other info:
make a directory structure as you will - feel free to ask for inclusion of external tools - but's let have a discussion on this first.

extract:
python script implementing a class that can extract type and key to a json string
including a simple main which can be called wity key and type

archives: 
trust no one - create script which will create a file in directory backups 
with the name archive_timestamp.csv where timestamp is a CCYYMMDD_HHMMSS timestamp


part 2:
start by making a plan - no coding for the following:
in the part above we took the files and loaded to archive.csv
now we want to process the harvested data meaning
for each record unzip the base64 encoded base64_json to a json dictionary
then find the json-entries with a path as described in "to_be_extracted.csv"
give me examples of a good input structure to the "path input" in "to_be_extracted.csv" 
inspirations for json's also to the archive above - well be inspired to input in what you find in ../duns_connect/cache - they are named .txt but are json's

part 3: 
now we adjusted the input - propose an example of "to_be_extracted.csv"

part 4:
cool now update the solution and directory structure to have a 
pass 1 reading input - compressing and storing in output for pass 1
pass 2 readint the output from pass 1 and storing in output directory for pass 2


part 5:
propose a plan before coding for pass 3 
the output from pass2 extracted.csv needs to be added to result file called full_extract.csv - again trust no one - we do not want to end up with a partly full_extract.csv file - if process interrupted before completed

part 6:
going all the way back to pass 1 - we need an identifier for the load - a run_id
the run_id should be a simple all the way to microseconds and readable i.e. at start up allocate a timestamp which will be tha same for all records harvested

part 7:
the src/field_extractor.py uses regular expression package in _traverse
plan a change where the extraction is done using the native json support.
i.e. uses json names in the dict structure to extract


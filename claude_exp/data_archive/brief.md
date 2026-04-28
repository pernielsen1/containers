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





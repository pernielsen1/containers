# intro
It's a long prompt whch may have inconsistiencis - read it evaluate and ask questions
## build archivedar
let's build an isolated archiving application in directory archive.
within archive we shuld have a archive.json file setting the input.
in the initial version it will have
"input_dir" set to the value of "output" in the current directory
"done_dir" set to the valud of "output/done" in currenct directory
"archive_index" set the value of "archive" in the current directory
"archive_data" set the value of "archive_data" in the current directory
all files in "input_dir" has the pattern
type_key_timestamp.* 
timestamp may or may not have '_' build in.  the next seperateor is the dot '.'
the application will read all files in "input_dir" and add them to a zip archive in "archive_data"
inside "archive_index" will be a csv file called "archive.csv" which contains:
type
key
timestamp 
file_name 
zip_archive_filename

# resilience importance
after having created the zip archive and created a "temp_index" - csv file containing the newly added files from "input_dir"
it's time to get critical 
we wants to:
- update the "master_archive_index.csv" file which is also stored in "archive_index" directory with the value of temp
- move all processed files from "input_dir" to "done_dir" 
and if process is interrupted just a simple restart of the script should achieve the end result
claude

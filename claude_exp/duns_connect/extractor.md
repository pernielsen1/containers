# extractor
so we have archived information using "Archiver" now we need a utility to extract
we need a utility extract.py which implemens a class Extract
Extract reads just like Archive a config.json file or a dict - which as minimum has the "archive_index" and "archive_data" tags.

Extract class has two parameters
--key 
--output_dir
if output_dir is not passed it may be configured in the passed json file or dictionary
the Extract will 
find all entries in master_archive_index.csv which mathes the key.
Extract the file which is stored in the zip-file according to the archive_index.csv
the extracted file should be stored in --output_dir and have the name which is just like it was archived originally
i.e. originally contructed from type_key_timestamp


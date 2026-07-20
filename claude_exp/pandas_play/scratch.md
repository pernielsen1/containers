# 99_extract
manually load the it is in same as gbc_indir (DUNS( hunt_duplicates/duplicates_gbc.csv
df_duplicates.gbc.
take the df_duplicates.gbc and let it only contain two fields CUST_ID and is_selected.
after the df_gbc has been read - do a merge to df_duplicates gbc left on CUST_ID.
make a field has_duplicates which should 1 if the cust_id exists in df_duplicates.gbc and df_gbc else 0


# new fields search
in 0_search_harvest.py extract 
* dunsControlStatus.operatingStatus.dnbCode
* dunsControlStatus.operatingStatus.description 
to the 0_search_results.csv 
verify spelling versus the example examples/search_json_K1.json


# divide and conquer
in 0_select.py the next step is divide the keys in different buckets by calculating a result for all keys (CUST_ID)
for each key calculate a result when a result criteria is fullfilled the key is closed if not go on with next criteria
## crierias in order of relevance
1. if a key has one row where the DUNS_NO has duplicate_points <> 0 then the result is "duplicate" 
2. if a key has one row with only_one_nat_id_and_name <> 0 and known_parent_points <> 0 then result is "platinum_plus"
3. if a key has one row with only_one_nat_id_and_name <> 0 then result is "platinum-plus"
4. if a key has more than one row with via_nat_id but has at least one with via_name giving the same duns_no then the result is "gold" if the duns_no has known_parent_points <> 0 then result is "gold_plus"
5. if a key has one row only in via_nat_id an no matches on via_name than result is "silver".
6. if a key has no rows with via_nat_id but has a match on via_name where the first 5 letters (remove blanks) of the searched name equals the returned name and the postal code is an exact match then the result is "bronze"
7. if no result has been provided so far the result is "other"

After having calculated the result create output/0_search/buckets.csv with
input_data for the key from search_input.csv the result field and the information from  search_select.csv for the found DUNS-rows with following rules
1. duplicate write the first row where the duplicate was identified
2. platinum or platinum_plus write the via_nat_id row
3. gold or gold_plus write the first row from via_name where the duns_no was also found in via_nat_id.
4. silver write the via_nat_id row
5. bronze write all rows fulfilling the bronze criterias
6. other write all rows for the key.

# no_duns_confirmed
new input file input/confirmed_no_duns.csv has two columns key and comment - I have created the first input for both test and prod.

current selection priority rules for result starts with duplicate, platinum_plus but there is a new rule with higher priority
if key exists in input/confirmed_no_duns.csv then the winner is "confirmed_no_duns"
for confirmed_no_duns - 
if the result is "confirmed_no_duns" then write all rows to buckets.csv with result "confirmed_no_duns"

## update duns
create new script 0_search_update_duns.py
select from output/0_search/buckets.csv
for rows with platinum, platinum_plus, gold, gold_plus
copy the row and write to output/0_search/update_duns.csv  

## update duns to mdm 
create new script 3_update_duns.py
in init create use the "to_object".. 
read output/0_search/update_duns.csv 
for each call method with
this returns a text line write it to 
output/3_to_xx 

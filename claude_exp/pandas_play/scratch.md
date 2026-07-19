# 99_extract
see mail

# new fields search
in 0_search_harvest.py extract 
dunsControlStatus.operatingStatus.dnbCode
dunsControlStatus.operatingStatus.description 
to the 0_search_results.csv 
verify spelling versus the example examples/search_json_K1.json


# divide and conquer
in 0_select.py the next step is divide the keys in different buckets by calculating a result for all keys (CUST_ID)
for each key calculate a result when a result criteria is fullfilled the key is closed if not go on with next criteria
## criterias in order of relevance
if a key has one row where the DUNS_NO has duplicate_points <> 0 then the result is "duplicate" 
if a key has one row with only_one_nat_id_and_name <> 0 and known_parent_points <> 0 then result is "platinum_plus"
if a key has one row with only_one_nat_id_and_name <> 0 then result is "platinum-plus"
if a key has more than one row with via_nat_id but has at least one with via_name giving the same duns_no then the result is "gold" if the duns_no has known_parent_points <> 0 then result is "gold_plus"
if a key has one row only in via_nat_id an no matches on via_name than result is "silver".
if a key has no rows with via_nat_id but has a match on via_name where the first 5 letters (remove blanks) of the searched name equals the returned name and the postal code is an exact match then the result is "bronze"
if no result has been provided so far the result is "other"
after having calculated the result create output/0_search/buckets.csv with
input_data for the key from search_input.csv the result field and the information from select ??? search_results.csv for the found DUNS-rows.
duplicate write the first row where the duplicate was identified
platinum write the via_nat_id row
gold write the first row from via_name where the duns_no was also found in via_nat_id.
silver write the via_nat_id row
bronze write all rows fulfilling the bronze criterias
other write all rows for the key.

# change EU, EE, LT, GG
there are changes in the logic in ../../snippets/company_identifiers.py and also in the ../../snippets/tests/test_companyidentifiers.py
regard VAT_EE, VAT_LT and VAT_EU
these changes should also be implemented in our validate_vat_id.sql stored procedures both oracle and mysql. 
the containers are not started right now
make a plan for the changes.
also create a "freeze_py" directory which has the latest version (a copy) from the originals in ../../snippets - making it easier later to do a diff versus what is implemented in the sql stored procedures.
regarding GY to GG - country code GY renamed to GG GG_NAT_ID
#!/bin/bash
# https://www.ibm.com/docs/en/arl/9.7.0?topic=certification-extracting-certificate-keys-from-pfx-file
openssl rsa -pubin -in keys/RSA_Alice_Public.pem -text  -noout
read -p "Press enter to continue"
openssl rsa -in keys/RSA_Alice_Private_no_encryption.pfx -text -noout
read -p "Press enter to continue"
openssl rsa -in keys/RSA_Alice_Private_no_encryption.pem -text -noout

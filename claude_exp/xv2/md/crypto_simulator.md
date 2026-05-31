# crypto_simulator backend
## crypto_host
crypto_host implemented gets the f2 and f47 as input and the intention is that the crypto_host can perform necessary validations
## f47 a json string containing following tags
f52 the pin block in base64
f14 is the expiry date
f55 should contain the subfields needed for an iso8583 arqc calculation.
suggest a json structure for f55

## encapsulate all in f47
the f55 json structure should be include in f47 together with f14, f52, message type (0100, 0110), cvv2 and aav (base64)
suggest a json structure for the f47 carrying it all

## store in f47.json
store this structure in f47.json

# build an implementation of crypto backend
suggest a plan for implementing the real crypto backend - we are operating in the MasterCard scheme
f47 input should be updated with also having the response code 
if f52 is existing in f47 perform a pin verification - the correct pin for the card can be found in pans_defined.json for f2
if f55 exists and message type is 0100 calculate the cryptogram element of f55
if f55 exists and message type is 0110 calculate the arpc element 
if cvv2 is existing perform a cvv verification
if aav is existing perform an aav verification
when calculations are performed the response OK plus in the case of ARPC the actual arpc value in base64 should be present
the plab should also include a plan for test cases which - using the existing pans_defined.json and test_csv.files - there create a new test file which contains the crypto_test cases test_crypt.csv
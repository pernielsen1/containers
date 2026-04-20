prereq - I installed flask

let us build a fortanix simulator inspired by the fortanix dsm
https://support.fortanix.com/docs/plugins-getting-started
I don't need the full implementation just the possibility to invoke a plugin.
the actual implementation of the plugin in the simulator will be a python script.
Initially to get going implement a plug-in in our simulator called upper_case which does just that i.e. returns the upper case of the input string
create a test script which using curl can run the upper_case plug in after having retrieved the login credentials

further instructions 1:
let's add another simple plugin lower_case which does just that - i.e. translates input to lower case - now for this one the input will be a dictionary containing the tag input which contains the string to be translated to lower case.
the function should return a dict with two items "result_bool" which is true if plugin completes OK and false if not and the item "result_string" containing the result of the lowercase translation.
Now if the input string is "42_IS_UPPER_CASE" then the plugin should fail - with an error message - "42 can never be lower case" the error message should be in the return dict in tag "error"
add the plugin including test cases

further instructions 2:
OK we have a server - now we need to make it into a test server for crypto operations.
the operations we will initally need is DES & AES availability. 
the server should contain a key store (we are testing so it is initially loaded as a json file)

key store should have keys which should all be items with (name, value) value is the key in base64

it shall be possible to create a derive a key from another key into the key store - so a key can be referenced with a token_id which is either the name found in the json file or a derived id as a result of a "derive key".
initially make a very simple derive_key taking input "diversify" and keyname, and returns a key token which is "diversify" + key name.  The value for the key will be the key value for the key name xored with the diversify parameter. 

and we need the basic plugin do_cipher who takes the following input
key_token: the name of the key
algorithm: either "DES" or "AES"
data : the data in base64 string format
key_name: the key name already existing in keystore
iv: the initial vector value - if not passed assume hex 00 in all bytes

the result data in a dict should be the encrypted value in base64 format 

Great crypto basics in place
Let us try the classical case of a pin block (field 52) in ISO8583
the test case is PAN="555551234567890" PIN="1234"
so let's assume the pin block in incoming is encrypted with the "des_key" from keystore.json and should be translated to being encrypted under "des_key_out" a new key with the value (hex) C1C1C1C1C1C1C1C11C1C1C1C1C1C1C1C




import json
import base64
import pn_utilities.logger.PnLogger as PnLogger
from ff3 import FF3Cipher

log = PnLogger.PnLogger()

#-----------------------------------------------
# test_fpe - create 1 million different values
# pip3 install ff3
#-----------------------------------------------
def test_fpe():
    key = "EF4359D8D580AA4F7F036D6F04FC6A94"
    tweak = "D8E7920AFA330A73"
    
    # Create an FPE cipher object
    cipher = FF3Cipher(key, tweak, radix=10)
    # make 0 to 999999 (one million entries) in output.csv
    outfile = open("output.csv","w")
    num_entries = 1000000
    for num in range(num_entries):  # Looping through 000 to 999999
        formatted_num = f"{num:06}"  # Ensure six character format
        encrypted_num = cipher.encrypt(formatted_num)
        decrypted_num = cipher.decrypt(encrypted_num)
        outfile.write(formatted_num + ";" + encrypted_num + ";" + decrypted_num + "\n")

    outfile.close()


#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
    log.info("here we go")
    test_fpe()
 
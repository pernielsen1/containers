#-----------------------------------------------------
# pip install pyOpenSSL
#-----------------------------------------------------

#--------------------------------------------------------
# START OF DIRTY
# OK this is dirty .. we will go directy to the package in the source instead of the installed version of pn_utilities.

import sys
import os
sys.path.insert(0, '../..')
# END OF DIRTY

import pn_utilities.crypto.PnCrypto as PnCrypto
import pn_utilities.logger.PnLogger as PnLogger

import base64
# from OpenSSL import crypto
# pip install cryptography
from cryptography.hazmat.primitives.serialization import pkcs12, load_der_private_key
from cryptography.hazmat.primitives import serialization
KEY_DIR = "keys/"
PFX_PASSWORD = b'pn_password'

def guess_type(pem):
  if (pem.find("BEGIN EC PRIVATE") > 0):
    return "EC_PRIVATE"
  if (pem.find("BEGIN PRIVATE") > 0):
    return "RSA_PRIVATE"
  if (pem.find("BEGIN PUBLIC") > 0):
    return "PUBLIC"
  # still here = not found 
  return None

  
def extract_key(PC_obj, name):
  my_keys = PC_obj.get_PnCryptoKeys()
  key_val = my_keys.get_key(name).get_value()
  type = guess_type(key_val)
  clean_pem = PC_obj.clean_pem(key_val)
  der = base64.b64decode(clean_pem)
  if ( type == "RSA_PRIVATE" or type == "EC_PRIVATE"):
    log.info("extracting PRIVATE key for:" + name)
    private_key = load_der_private_key(der, None)
    friendly_name = name.encode('utf-8')
    p12data = pkcs12.serialize_key_and_certificates(friendly_name, private_key, None, None,
                                                  serialization.BestAvailableEncryption(PFX_PASSWORD) )
    pfx_file_name = (KEY_DIR + name + '_encrypted.pfx')
    with open(pfx_file_name, 'wb') as pfxfile:
      pfxfile.write(p12data)
      log.info("Extracted " + name + " to " + pfx_file_name)

    p12data = pkcs12.serialize_key_and_certificates(friendly_name, private_key, None, None,
                                                  serialization.NoEncryption() )
    pfx_not_encrypted_file_name = (KEY_DIR + name + '_no_encryption.pfx')
    with open(pfx_not_encrypted_file_name, 'wb') as pfxfile:
      pfxfile.write(p12data)
      log.info("Extracted not encrypted " + name + " to " + pfx_not_encrypted_file_name)

    pem_data = private_key.private_bytes(
          encoding=serialization.Encoding.PEM,
          format=serialization.PrivateFormat.PKCS8,
          encryption_algorithm = serialization.NoEncryption() 
    )

    pem_file_name = (KEY_DIR + name + '_no_encryption.pem')
    with open(pem_file_name, 'wb') as pemfile:
      pemfile.write(pem_data)
      log.info("Extracted " + name + " to " + pem_file_name)

    #      serialization.BestAvailableEncryption(b'mypassword')
    return
  if ( type == "PUBLIC" ):
    log.info("extracting PUBLIC key for:" + name)
    public_key = serialization.load_der_public_key(der, None)

    pem_data = public_key.public_bytes(
      encoding=serialization.Encoding.PEM,
      format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    pem_file_name = (KEY_DIR + name + '.pem')
    with open(pem_file_name, 'wb') as pemfile:
      pemfile.write(pem_data)
      log.info("Extracted " + name + " to " + pem_file_name)
    return
  
  log.error("Not able to guess the type of key for:" + name)
  return 



#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  print(os.getcwd())
  log = PnLogger.PnLogger()
  my_crypto = PnCrypto.PnCrypto()  # use default config.jsonfile
  extract_key(my_crypto, "RSA_Alice_Public")
  extract_key(my_crypto, "RSA_Alice_Private")
  extract_key(my_crypto, "EC_Alice_Private")
  extract_key(my_crypto, "RSA_Bob_Public")
  extract_key(my_crypto, "RSA_Bob_Private")
  extract_key(my_crypto, "EC_Bob_Private")

#  os.chdir(sys.path[0])
#  do_it()

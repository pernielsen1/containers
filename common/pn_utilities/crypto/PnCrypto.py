
import json
from Crypto.Cipher import AES
from Crypto.Cipher import DES
from Crypto.Cipher import DES3
from Crypto.PublicKey import ECC
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP
from Crypto.Hash import SHAKE256, SHA256
from Crypto.Protocol.DH import key_agreement
from Crypto.Hash import CMAC
from Crypto.Util.Padding import pad
from Crypto.Util.Padding import unpad
from Crypto.Signature import pkcs1_15
from Crypto.Signature import DSS

DATA_DIR = '../data/'
import pn_utilities.PnLogger as PnLogger
logger = PnLogger.PnLogger()
#------------------------------------------
# PnCryptKey - the key object
#------------------------------------------
class PnCryptKey():
    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)
    def __init__(self, name="", value="", type=""):
        self.key = {}
        self.key['name'] = name
        self.key['value'] = value
        self.key['type'] = type

    def get_name(self):
        return str(self.key['name'])
    def get_value(self):
        return self.key['value']
    def get_type(self):
        return self.key['type']
    def get_key(self):
        return self.key
#---------------------------------------------------------
# PnCryptKeys - load the keys from the data store to 
#---------------------------------------------------------
class PnCryptoKeys:
    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)

    def __init__(self, config_file="", name=""):
        self.keys = {}
        self.name = name
        if (config_file == ""):
            config_file = DATA_DIR + "PnCryptoKeys.json"

        logger.info("Loading keys store from:" + config_file)
        with open(config_file, 'r') as file:
            dict = json.loads(file.read())    
            input_keys = dict['crypto_keys']
            for k in input_keys:
                self.keys[k] = PnCryptKey(k, input_keys[k], "a type")

    def get_keys(self):
        return self.keys
    
    def import_ephemeral_key(self, value, type):
        key_no = len(self.keys) + 1
        key_name= "eph_" + str(key_no)
        self.keys[key_name] = PnCryptKey(key_name, value, type)
        return self.keys[key_name]

    def get_key(self, key_name):
        return self.keys.get(key_name, None)
        
    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)
#-------------------------------------------------------------
# do_dummy
#-------------------------------------------------------------
class PnCrypto(): 
    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)
    def __init__(self, config_file="", name=""):
        self.keys = PnCryptoKeys(config_file=config_file, name=name)
    def get_PnCryptoKeys(self):
        return self.keys
    #-------------------------------------------------------------
    # do_DES  - the key can be a name or a PnCryptoKey
    #-------------------------------------------------------------
    def do_DES(self, operation, key, mode, data, iv):
        if  isinstance(key, PnCryptKey):
            k = key
        else:
            k = self.keys.get_key(key)
        key_value = k.get_value()
        if len(key_value) == 32 :
            key_value = key_value + key_value[0: 16]  # double des set k3 = K1 

        if (len(key_value) == 16):
            des_obj = DES
        else:
            des_obj = DES3
        key_token = bytes.fromhex(key_value)

        if (mode == "ECB" and operation != 'mac'):
            cipher_obj = des_obj.new(key_token, des_obj.MODE_ECB)
        if (mode == "CBC" and operation != 'mac'):
            iv_bin = bytes.fromhex(iv)
            cipher_obj = des_obj.new(key_token, des_obj.MODE_CBC, iv=iv_bin)

        data_bin = bytes.fromhex(data)
        if (operation == "encrypt"):
            return cipher_obj.encrypt(data_bin).hex()
        if (operation == "decrypt"):
            return cipher_obj.decrypt(data_bin).hex()
        if (operation == "mac"):
            cobj = CMAC.new(key_token, ciphermod=des_obj)
            cobj.update(data_bin)
            return cobj.hexdigest()
        # still here something wrong 
        return "Invalid operation"
    #---------------------------------------------------------------------
    # hex_string_xor(s1, s2)
    # https://stackoverflow.com/questions/52851023/python-3-xor-bytearrays
    #---------------------------------------------------------------------
    def hex_string_xor(self, s1, s2):
        one = bytes.fromhex(s1)
        two = bytes.fromhex(s2)
        one_xor_two = bytes(a ^ b for (a, b) in zip(one, two))
        return one_xor_two.hex()


    #-------------------------------------------------------------
    # udk
    #-------------------------------------------------------------
    def do_udk(self, imk_name, pan, psn):
#        keystore = self.get_PnCryptoKeys()
        pan_psn = pan + psn;
        pan_psn = pan_psn[len(pan_psn) -16: len(pan_psn)]
        iv = "0000000000000000"
#        imk_key = keystore.import_ephemeral_key(imk.)
        left  = self.do_DES('encrypt', imk_name, 'ECB', pan_psn, iv)
        pan_psn_xor = self.hex_string_xor(pan_psn, "FFFFFFFFFFFFFFFF")
        right = self.do_DES('encrypt', imk_name, 'ECB', pan_psn_xor, iv)
        return left + right
    #-------------------------------------------------------------
    # session_key
    #-------------------------------------------------------------
    def do_session_key(self, imk, pan, psn, atc):
        udk_value  = self.do_udk(imk, pan, psn)
        udk_key = self.get_PnCryptoKeys().import_ephemeral_key(udk_value, 'DES')
        f1 = atc + "F0" + "0000000000"
        f2 = atc + "0F" + "0000000000"
        iv = "0000000000000000"
        left  = self.do_DES('encrypt', udk_key, 'ECB', f1, iv)
        right = self.do_DES('encrypt', udk_key, 'ECB', f2, iv)
        return left + right
#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
    my_keys = PnCryptoKeys()
#    print(my_keys.get_keys()) 
    k = my_keys.get_key('k3') 
    print(k.get_name())
    print(k.get_value())
    print(k.get_type())

    print(my_keys.get_key('k3xyz')) 
    my_PnCrypto = PnCrypto()
#    res = my_PnCrypto.do_DES("encrypt", "DES_k1", "ECB", "6bc1bee22e409f96e93d7e117393172a", "0000000000000000") 
#     print("res" + res + " exp:DF8F88432FEA610CC1FAAF1AB1C0C037") 
    res = my_PnCrypto.do_udk('IMK_k1','5656781234567891' , '01')
    print("res" + res + "Exp: CB45F993BDDA763EF030AF6CE1762735" )
    res = my_PnCrypto.do_session_key('IMK_k1','5656781234567891' , '01', '0001')
    print("res" + res + "Exp: E011BB83D8A60BEE3CDE768F68560BD9")
 
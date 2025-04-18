
import json
import base64

from pn_utilities.crypto.PnCryptoKeys import PnCryptoKeys
from pn_utilities.crypto.PnCryptoKeys import PnCryptKey
from Crypto.Random import get_random_bytes

# from Crypto.Cipher import AES
from Crypto.Cipher import DES
from Crypto.Cipher import DES3
from Crypto.Hash import CMAC

# from Crypto.PublicKey import ECC
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
from Crypto.Cipher import PKCS1_OAEP
from Crypto.Hash import SHAKE256, SHA256
# from Crypto.Protocol.DH import key_agreement
# from Crypto.Util.Padding import pad
# from Crypto.Util.Padding import unpad
# from Crypto.Signature import pkcs1_15
# from Crypto.Signature import DSS
from ff3 import FF3Cipher

PN_CRYPTO_KEYS = "pn_crypto_keys"
PN_CRYPTO_DATABASE = "pn_crypto_key_store"

import pn_utilities.logger.PnLogger as PnLogger
logger = PnLogger.PnLogger()
config = {}
#-------------------------------------------------------------
# PnCrupto the class capsulating the crypto functions
#-------------------------------------------------------------
class PnCrypto(): 
    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)
    # the init load the config file to dict config.
    def __init__(self, config_file="", id=""):
        if (config_file == ""):
            config_file = "config.json"
        with open(config_file, 'r') as file:
            self.config = json.loads(file.read())    
        self.keys = PnCryptoKeys(self.config)

    def get_PnCryptoKeys(self):
        return self.keys
    #--------------------------------------
    # key can be:  
    #   Instance of Key 
    #   id of key in key store 
    #   or the raw key value
    #--------------------------------------
 
    def get_key_value(self, key):
        if  isinstance(key, PnCryptKey):
            return key.get_value()
        else:
            k = self.keys.get_key(key)
            if ( k != None):
                return k.get_value()
            else: # the key is assumed to be the raw value
                return key
    #-----------------------------------------------------------
    # do_RSA
    #------------------------------------------------------------
    def do_RSA(self, operation, key, data, mode="OAEP", hash="SHA256"):
        # ToDo look up SHA function object based on name
        rsa_key = RSA.import_key(base64.b64decode(self.clean_pem(key)))     
        if (mode == "OAEP"):
            label=""
            hash_obj = SHA256.new()
            cipher_rsa = PKCS1_OAEP.new(key=rsa_key, hashAlgo=hash_obj, label=label)
        if (mode == "PKCS1_v1_5"):
            cipher_rsa =  PKCS1_v1_5.new(rsa_key)        

        label=""
        data_bytes = bytes.fromhex(data)
        if (operation == "encrypt"):
            return cipher_rsa.encrypt(data_bytes).hex()
        if (operation == "decrypt"):
            if (mode == "OAEP"):
                return cipher_rsa.decrypt(data_bytes).hex()
            if (mode == "PKCS1_v1_5"):
                sentinel = get_random_bytes(16)
                return cipher_rsa.decrypt(data_bytes, sentinel).hex()

        return "Wrong operation"
 

    #-------------------------------------------------------------
    # do_DES  - the key can be a id or a PnCryptoKey
    #-------------------------------------------------------------
    def do_DES(self, operation, key, mode, data, iv):
        key_value = self.get_key_value(key)
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
    def do_udk(self, imk_id, pan, psn):
        pan_psn = pan + psn;
        pan_psn = pan_psn[len(pan_psn) -16: len(pan_psn)]
        iv = "0000000000000000"
        left  = self.do_DES('encrypt', imk_id, 'ECB', pan_psn, iv)
        pan_psn_xor = self.hex_string_xor(pan_psn, "FFFFFFFFFFFFFFFF")
        right = self.do_DES('encrypt', imk_id, 'ECB', pan_psn_xor, iv)
        return left + right
    #-------------------------------------------------------------
    # session_key
    #-------------------------------------------------------------
    def do_session_key(self, imk, pan, psn, atc):
        udk_value  = self.do_udk(imk, pan, psn)
        f1 = atc + "F0" + "0000000000"
        f2 = atc + "0F" + "0000000000"
        iv = "0000000000000000"
        left  = self.do_DES('encrypt', udk_value, 'ECB', f1, iv)
        right = self.do_DES('encrypt', udk_value, 'ECB', f2, iv)
        return left + right

    #------------------------------------------------------------
    # mypad: do an EMV pad
    #------------------------------------------------------------
    def mypad(self, data, block_size):
        num_to_pad = block_size - (len(data) % block_size)
        eight_zeroes = "0000000000000000" 
        if (num_to_pad == block_size):
            return data
        else: 
            eight_zeroes = "0000000000000000" 
            pad_data = eight_zeroes[0: num_to_pad]
            return data + pad_data
    #------------------------------------------------------------
    # man_mac do a mac 
    #------------------------------------------------------------
    def man_mac(self, key, data):
        left = key[0:16]
        num_iter = int(len(data) / 16) - 1
        iv = "0000000000000000"
        data_block = data[0:16]
        for i in range(num_iter):
            data_block = self.do_DES('encrypt', left, 'ECB', data_block, iv)
            xor1 = data_block
            start = (i + 1) * 16
            xor2 = data[start: start  + 16]
            data_block = self.hex_string_xor(xor1, xor2)
        return data_block
    #------------------------------------------------------------
    # do_arqc 
    #------------------------------------------------------------
    def do_arqc(self, imk, pan, psn, atc, data, add80):
        sk = self.do_session_key(imk, pan, psn, atc)
        if (add80):
            data = data + "80"
        data = self.mypad(data, 16)
        iv = "0000000000000000"
        left = sk[0:16]
        # do a normal DES CBC encrypt of all blocks except the last block
        mac_data = data[0: len(data) - 16]
        enc2 = self.do_DES('encrypt', left, 'CBC', mac_data, iv)
        # take last block of encrypted data and xor with the last block of the data (last 8 bytes)
        last_block_in_enc = enc2[len(enc2) - 16:len(enc2)]
        last_plain_block = data[len(data)-16:len(data)]
        enc_mac = self.hex_string_xor(last_plain_block, last_block_in_enc)
        man_mac_val = self.man_mac(sk, data)
        arqc = self.do_DES('encrypt', sk, 'CBC', enc_mac, iv)
        return arqc 

    #-------------------------------------------------------------
    # do_arpc
    #-------------------------------------------------------------
    def do_arpc(self,imk, pan, psn, atc, arqc, csu):
        sk = self.do_session_key(imk, pan, psn, atc)
        x = csu + "000000000000"
        y = self.hex_string_xor(arqc, x)
        return self.do_DES('encrypt', sk, 'ECB', y, "")

    def clean_pem(self, s):
        s = s.replace("-----BEGIN EC PRIVATE KEY-----", "")
        s = s.replace("-=-----END EC PRIVATE KEY-----", "")
        s = s.replace("-----BEGIN PUBLIC KEY-----", "")
        s = s.replace("-----END PUBLIC KEY-----", "")
        s = s.replace("-----BEGIN PRIVATE KEY-----", "")
        s = s.replace("-----END PRIVATE KEY-----", "")
        return s

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

 #   test_fpe()
    my_PnCrypto = PnCrypto()
    my_keys = my_PnCrypto.get_PnCryptoKeys()
    k = my_keys.get_key('k3') 
    print(k.get_id())
    print(k.get_value())
    print(k.get_type())

#    res = my_PnCrypto.do_DES("encrypt", "DES_k1", "ECB", "6bc1bee22e409f96e93d7e117393172a", "0000000000000000") 
#     print("res" + res + " exp:DF8F88432FEA610CC1FAAF1AB1C0C037") 
    res = my_PnCrypto.do_udk('IMK_k1','5656781234567891' , '01')
    print("res" + res + " Exp: CB45F993BDDA763EF030AF6CE1762735" )
    res = my_PnCrypto.do_session_key('IMK_k1','5656781234567891' , '01', '0001')
    print("res" + res + " Exp: E011BB83D8A60BEE3CDE768F68560BD9")
    data = "00000000510000000000000007920000208000094917041900B49762F2390000010105A0400000200000000000000000"
    res = my_PnCrypto.do_arqc('IMK_k1','5656781234567891' , '01', '0001', data, True)
    print("res:" + res +  " exp: F5EB72ED4F51B9DE" )
    res = my_PnCrypto.do_arpc('IMK_k1','5656781234567891' , '01', '0001', 'F5EB72ED4F51B9DE', '0012')
    print("res:" + res +  " exp: A2092CCC0C25006B" )
    r_json = my_PnCrypto.get_PnCryptoKeys().get_keys_json()
    print(r_json)
    r_json = my_PnCrypto.get_PnCryptoKeys().get_key_json("IMK_k1")
    print(r_json)



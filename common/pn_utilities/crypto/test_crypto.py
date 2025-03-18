# crypto test cases
# pip install pycryptodome
# https://pycryptodome.readthedocs.io/en/latest/src/hash/cmac.html
# https://medium.com/baybaynakit/emv-key-types-and-derivation-d0cca3ab2c6d
# https://medium.com/baybaynakit/how-to-use-emv-keys-9a1f908b12b3
# https://stackoverflow.com/questions/6055763/how-can-i-do-an-iso-9797-1-mac-with-triple-des-in-cx§
# https://neapay.com/online-tools/calculate-cryptogram.html?amountValue=000000005100&amountoValue=000000000000&countryCodeValue=0792&tvrValue=0000208000¤cyCodeValue=0949&trandateValue=170419&tranTypeValue=00&unValue=B49762F2&aipValue=3900&atcValue=0001&iadValue=0105A040000020000000000000000080&padValue=8000000000000000&ivValue=00000000000000000000000000000000&mkValue=0123456789abcdeffedcba9876543210&panValue=5656781234567891 00&psnValue=01
# https://github.com/wolf43/AES-GCM-example/blob/master/aes_gcm.py
# ToDo:
#   add label in OAEP test cases plus AAD  function... 
#   ECDSA - samples.


import os
import json
import base64
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


#------------------ GLOBALS ---------------------------
config_dir = 'crypto/'
config_file = 'test_crypto.json'
segment_to_run = 'ECC'
segment_to_run = 'RSA_SIGNATURES'
segment_to_run = 'ECC_SIGNATURES'

# segment_to_run = 'ALL'


crypto_handle = None # just a dummy global object
#------------------------------------------------------------
# crypto_jsd - defining interface to crypto package
#-------------------------------------------------------------
class crypto_hsm:
    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)
    def __init__(self, name):
        self.name = name
    def get_name(self):
        return self.name
    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)
    #-------------------------------------------------------------
    # do_DES
    #-------------------------------------------------------------
    def do_DES(self, operation, key_value, mode, data, iv):
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
    #-------------------------------------------------------------
    # do_aes
    #-------------------------------------------------------------
    def do_AES(self, operation, key_value, mode, data, iv):
        key_bin = bytes.fromhex(key_value)
        if (operation == "decrypt" and mode== "GCM"):
            tag_hex = data[len(data) - 32: len(data)]
            cipher_hex = data[0: len(data) - 32]
            data_bin = bytes.fromhex(cipher_hex)
            tag_bin = bytes.fromhex(tag_hex)
        else:
            data_bin = bytes.fromhex(data)

        if (mode == "ECB"):
            cipher_obj= AES.new(key_bin, AES.MODE_ECB)
        if (mode == "CBC"):
            iv_bin = bytes.fromhex(iv)
            cipher_obj= AES.new(key_bin, AES.MODE_CBC, iv=iv_bin)
        if (mode == "GCM"):
            # Encrypt using AES GCM
            nonce_bin = bytes.fromhex(iv)
            cipher_obj = AES.new(key_bin, AES.MODE_GCM, nonce = nonce_bin)
            # cipher.update(aad)
          
        if (operation == "encrypt"):
            if mode != "GCM":
                return cipher_obj.encrypt(pad(data_bin, AES.block_size)).hex()
            else:
                ciphertext, tag = cipher_obj.encrypt_and_digest(data_bin)
                return ciphertext.hex() + tag.hex()
        
        if (operation == "decrypt"):
            if mode != "GCM":
                return unpad(cipher_obj.decrypt(data_bin), len(key_bin)).hex() 
            else:
                return cipher_obj.decrypt_and_verify(data_bin, tag_bin).hex()
 
        if (operation == "mac"):
            return "MAC to be done"
        # still here something wrong 
        return "Invalid operation"
    #-------------------------------------------------------------
    # do_hash
    #-------------------------------------------------------------
    def do_hash(self, mode, data):
        bin_data = bytes.fromhex(data)
        if (mode == "SHA256"):
            hash_object = SHA256.new(bin_data)
        return hash_object.hexdigest()

    
    #-------------------------------------------------------------
    # do_ECC
    #-------------------------------------------------------------
    def kdf_raw(self, x):
         return x
    #-------------------------------------------------------------
    # do_ECC
    #-------------------------------------------------------------
    def do_ECC_shared_secret(self, priv_key, pub_key):
        pub_k =  ECC.import_key(base64.b64decode(clean_pem(pub_key)))
        priv_k = ECC.import_key(base64.b64decode(clean_pem(priv_key)))
        # derive the raw shared secret with dummy kdf function (kdf_raw)
        session_key = key_agreement(static_priv=priv_k, static_pub=pub_k, kdf=self.kdf_raw)
        return session_key.hex()
    #-------------------------------------------------------------
    # do_ECC
    #-------------------------------------------------------------
    def do_ECC_with_kdf(self, priv_key, pub_key, algo, prepend, append):
        session_key = self.do_ECC_shared_secret(priv_key, pub_key)
        data_to_hash = prepend + session_key + append
        return self.do_hash(algo, data_to_hash)
    #-------------------------------------------------------------
    # do_RSA
    #-------------------------------------------------------------
    def do_RSA(self, operation, key, data):
        # Pycryptodome only supports the OAEP version
        label=""
        hash_obj = SHA256.new()
        rsa_key = RSA.import_key(base64.b64decode(clean_pem(key)))
        cipher_rsa = PKCS1_OAEP.new(key=rsa_key, hashAlgo=hash_obj, label=label)
        data_bytes = bytes.fromhex(data)
        if (operation == "encrypt"):
            return cipher_rsa.encrypt(data_bytes).hex()
        if (operation == "decrypt"):
            return cipher_rsa.decrypt(data_bytes).hex()

        return "Wrong operation"
    #-------------------------------------------------------------
    # do_RSA_SIGN
    #-------------------------------------------------------------
    def do_RSA_SIGN(self, key, hash, data):
        rsa_key = RSA.import_key(base64.b64decode(clean_pem(key)))
        bin_data = bytes.fromhex(data)
        hash_object = SHA256.new(bin_data)
        signature = pkcs1_15.new(rsa_key).sign(hash_object)
        return signature.hex()
    #-------------------------------------------------------------
    # do_RSA_VERIFY
    #-------------------------------------------------------------
    def do_RSA_VERIFY(self, key, hash, data, signature):
        rsa_key = RSA.import_key(base64.b64decode(clean_pem(key)))
        hash_obj = SHA256.new(bytes.fromhex(data))
        try:
            pkcs1_15.new(rsa_key).verify(hash_obj, bytes.fromhex(signature))
            return "ok"
        except (ValueError, TypeError):
            return "FAILED"
     #-------------------------------------------------------------
    # do_ECC_SIGN
    #-------------------------------------------------------------
    def do_ECC_SIGN(self, key, hash, data):
        key = ECC.import_key(base64.b64decode(clean_pem(key)))
        bin_data = bytes.fromhex(data)
        hash_obj = SHA256.new(bin_data)
        signer = DSS.new(key, "deterministic-rfc6979")

#        signer = DSS.new(key, 'fips-186-3')
        signature = signer.sign(hash_obj)
        return signature.hex()
    #-------------------------------------------------------------
    # do_ECC_VERIFY
    #-------------------------------------------------------------
    def do_ECC_VERIFY(self, key, hash, data, signature):
        key = ECC.import_key(base64.b64decode(clean_pem(key)))
        hash_obj = SHA256.new(bytes.fromhex(data))
        encoding = 'binary'
        try:
            DSS.new(key, mode='fips-186-3', encoding=encoding).verify(hash_obj, bytes.fromhex(signature))
            return "ok"
        except (ValueError, TypeError):
            return "FAILED"
            
def clean_pem(s):
    s = s.replace("-----BEGIN EC PRIVATE KEY-----", "")
    s = s.replace("-=-----END EC PRIVATE KEY-----", "")
    s = s.replace("-----BEGIN PUBLIC KEY-----", "")
    s = s.replace("-----END PUBLIC KEY-----", "")
    s = s.replace("-----BEGIN PRIVATE KEY-----", "")
    s = s.replace("-----END PRIVATE KEY-----", "")
    return s

#-------------------------------------------------------------
# udk
#-------------------------------------------------------------
def do_udk(imk, pan, psn):
    pan_psn = pan + psn;
    pan_psn = pan_psn[len(pan_psn) -16: len(pan_psn)]
    iv = "0000000000000000"
    left  = crypto_handle.do_DES('encrypt', imk, 'ECB', pan_psn, iv)
    pan_psn_xor = hex_string_xor(pan_psn, "FFFFFFFFFFFFFFFF")
    right = crypto_handle.do_DES('encrypt', imk, 'ECB', pan_psn_xor, iv)
    return left + right
#-------------------------------------------------------------
# session_key
#-------------------------------------------------------------
def do_session_key(imk, pan, psn, atc):
    udk  = do_udk(imk, pan, psn)
    r = atc + "000000000000"
    f1 = atc + "F0" + "0000000000"
    f2 = atc + "0F" + "0000000000"
    iv = "0000000000000000"
    left  = crypto_handle.do_DES('encrypt', udk, 'ECB', f1, iv)
    right = crypto_handle.do_DES('encrypt', udk, 'ECB', f2, iv)
    return left + right
#------------------------------------------------------------
# mypad: do an EMV pad
#------------------------------------------------------------
def mypad(data, block_size):
    num_to_pad = block_size - (len(data) % block_size)
    eight_zeroes = "0000000000000000" 
    if (num_to_pad == block_size):
        return data
    else: 
        eight_zeroes = "0000000000000000" 
        pad_data = eight_zeroes[0: num_to_pad]
        return data + pad_data
#-------------------------------------------------------------
# do_arqc
#-------------------------------------------------------------
def man_mac(key, data):
    left = key[0:16]
    num_iter = int(len(data) / 16) - 1
    iv = "0000000000000000"
    data_block = data[0:16]
    for i in range(num_iter):
        data_block = crypto_handle.do_DES('encrypt', left, 'ECB', data_block, iv)
        xor1 = data_block
        start = (i + 1) * 16
        xor2 = data[start: start  + 16]
        data_block = hex_string_xor(xor1, xor2)
    return data_block
            
def do_arqc(imk, pan, psn, atc, data, add80):
    sk = do_session_key(imk, pan, psn, atc)
    if (add80):
        data = data + "80"
    data = mypad(data, 16)
    iv = "0000000000000000"
    left = sk[0:16]
    # do a normal DES CBC encrypt of all blocks except the last block
    mac_data = data[0: len(data) - 16]
    enc2 = crypto_handle.do_DES('encrypt', left, 'CBC', mac_data, iv)
    # take last block of encrypted data and xor with the last block of the data (last 8 bytes)
    last_block_in_enc = enc2[len(enc2) - 16:len(enc2)]
    last_plain_block = data[len(data)-16:len(data)]
    enc_mac = hex_string_xor(last_plain_block, last_block_in_enc)
    man_mac_val = man_mac(sk, data)
    arqc = crypto_handle.do_DES('encrypt', sk, 'CBC', enc_mac, iv)
    return arqc 

#-------------------------------------------------------------
# do_arpc
#-------------------------------------------------------------
def do_arpc(imk, pan, psn, atc, arqc, csu):
    sk = do_session_key(imk, pan, psn, atc)
    x = csu + "000000000000"
    y = hex_string_xor(arqc, x)
    return crypto_handle.do_DES('encrypt', sk, 'ECB', y, "")

#---------------------------------------------------------------------
# hex_string_xor(s1, s2)
# https://stackoverflow.com/questions/52851023/python-3-xor-bytearrays
#---------------------------------------------------------------------
def hex_string_xor(s1, s2):
    one = bytes.fromhex(s1)
    two = bytes.fromhex(s2)
    one_xor_two = bytes(a ^ b for (a, b) in zip(one, two))
    return one_xor_two.hex()
#---------------------------------------------------------------------
# do_base64(opereation, data)  - data is hex string and returned as base or vise versa
#---------------------------------------------------------------------
def do_base64(operation, data):
    if (operation == "encode"):
        return base64.b64encode(bytes.fromhex(data)).decode("ascii")
    if (operation == "decode"):
        return base64.b64decode(data).hex()

#-------------------------------------------
# run_test: Run a crypto test case
#-------------------------------------------
def run_test(crypto_keys, tc):
    description = tc['description']
    alg =  tc['alg']
    expected_result = tc["expected_result"]
    if (alg != 'BASE64'):
        expected_result = expected_result.lower()
    result_str = ""
    if (alg == 'DES' or alg == 'AES'):
        if (alg == 'DES'):
            result_str = crypto_handle.do_DES(tc['operation'], crypto_keys[tc["key_name"]], tc['mode'], tc['data'], tc['IV'])
        if (alg == 'AES'): 
            result_str = crypto_handle.do_AES(tc['operation'], crypto_keys[tc["key_name"]], tc['mode'], tc['data'], tc['IV'])
    if (alg == "XOR"):
        result_str = hex_string_xor(tc["s1"], tc["s2"]) 
    if (alg == "BASE64"):
        result_str = do_base64(tc["operation"], tc["data"]) 
    if (alg == "UDK"):
        result_str = do_udk(crypto_keys[tc["key_name"]], tc['PAN'], tc['PSN'])
    if (alg == "SESSION_KEY"):
        result_str = do_session_key(crypto_keys[tc["key_name"]], tc['PAN'], tc['PSN'], tc['ATC'])
    if (alg == "ARQC"):
        result_str = do_arqc(crypto_keys[tc["key_name"]], tc['PAN'], tc['PSN'], tc['ATC'], tc['data'], True)
    if (alg == "ARPC"):
        result_str = do_arpc(crypto_keys[tc["key_name"]], tc['PAN'], tc['PSN'], tc['ATC'],tc['ARQC'], tc['CSU'])
    if (alg == "ECC_RAW"):
        result_str = crypto_handle.do_ECC_shared_secret(crypto_keys[tc["private_key"]], crypto_keys[tc["public_key"]]) 
    if (alg == "ECC_KDF"):
        result_str = crypto_handle.do_ECC_with_kdf(crypto_keys[tc["private_key"]], crypto_keys[tc["public_key"]], tc['algo'], tc['prepend'], tc['append'])
    if (alg == "HASH"):
        result_str = crypto_handle.do_hash(tc['mode'],tc['data'])
    if (alg == "RSA"):
       result_str = crypto_handle.do_RSA(tc['operation'], crypto_keys[tc["key"]], tc['data']) 
       if (tc['operation'] == "encrypt"):
            # OAEP has random element so we have to decrypt to verify with verify_key against plain message
            result_str = crypto_handle.do_RSA("decrypt", crypto_keys[tc["verify_key"]], result_str)
    if (alg == "RSA_SIGN"):
       result_str = crypto_handle.do_RSA_SIGN(crypto_keys[tc["key"]], tc['hash'], tc['data']) 
    if (alg == "RSA_VERIFY"):
       result_str = crypto_handle.do_RSA_VERIFY(crypto_keys[tc["key"]], tc['hash'], tc['data'], tc['signature'])
    if (alg == "ECC_SIGN"):
       result_str = crypto_handle.do_ECC_SIGN(crypto_keys[tc["key"]], tc['hash'], tc['data']) 
    if (alg == "ECC_VERIFY"):
       result_str = crypto_handle.do_ECC_VERIFY(crypto_keys[tc["key"]], tc['hash'], tc['data'], tc['signature'])

    if (result_str == expected_result):
        return True, "passed:" + description
    else:
        return False, "failed:" + description + " result_str:" + result_str + " expected:" + expected_result
#-----------------------------------------------------------------------------------------
# load config ... load the test_rest.json who has the test cases and connection details.
#-----------------------------------------------------------------------------------------
def load_config():
    with open(config_dir +  config_file, 'r') as file:
        return json.loads(file.read())    
#--------------------------------------------------------------------------------------
# run_tests:  Run all tests in the config['tests'l
#-----------------------------------------------------------------------------------------
def run_tests(config, segment):
    num_passed = 0
    num_failed = 0       
    num_cases =  0
    crypto_keys = config['crypto_keys']
    for key in config['tests']:
        if (segment == "ALL" or str(key) ==   segment ):
            segment_selected =  str(key)    
            for testkey in config['tests'][segment_selected]:
                num_cases = num_cases + 1
                tc = config['tests'][segment_selected][str(testkey)]
                result, msg = run_test(crypto_keys, tc)
                if (result):
                    num_passed = num_passed + 1
                else:
                    print(msg )
                    num_failed = num_failed + 1
  
    print("num_cases:" + str(num_cases) + " num_passed:" + str(num_passed) + " num_failed:" + str(num_failed))

# here we go
print('current directory:' + os.getcwd())
config = load_config()
crypto_handle = crypto_hsm("my_hsm")
run_tests(config, segment_to_run)

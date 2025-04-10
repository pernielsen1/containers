#-----------------------------------------------------
# articles on the test patterns
# https://docs.python.org/3/library/unittest.html

#--------------------------------------------------------
# START OF DIRTY
# OK this is dirty .. we will go directy to the package in the source instead of the installed version of pn_utilities.
# 
import sys, os
sys.path.insert(0, '../..')
# END OF DIRTY
#----------------------------------------------------------
#  

import unittest
import json
import pn_utilities.crypto.PnCrypto as PnCrypto
import pn_utilities.PnLogger as PnLogger

#-------------------------------------------------------------------
# 
#-------------------------------------------------------------------
class TestPnCrypto(unittest.TestCase):
  log = PnLogger.PnLogger()
 
  @classmethod
  def setUpClass(cls):
      cls.log.info("setUp starting")
      cls.my_crypto = PnCrypto.PnCrypto()  # use default config.jsonfile
      cls.my_keys = cls.my_crypto.get_PnCryptoKeys()
      cls.my_crypto_mysql = PnCrypto.PnCrypto("config_mysql.json")  # use default config.json file

      with open("test_PnCrypto.json", 'r') as file:
        cls.crypto_cases = json.loads(file.read())    
      
      cls.log.info("setUp completed starting tests")    

  def test_get_key(self):
      k = self.my_keys.get_key("k3")
      self.assertEqual(k.get_id(), 'k3')
      self.assertEqual(k.get_value(), '42c1bee22e409f96e93d7e117393172a')
      self.assertEqual(k.get_type(), 'a type')
      self.assertEqual(self.my_keys.get_key('Unknown key'), None)
      k1 = self.my_keys.get_key("DES_k1")
      
  # testing import key in my_crypto_keys.
  def test_import_key(self):
      
      keys= self.my_crypto_mysql.get_PnCryptoKeys()

      keys.delete_key('test_keyx')
      # detele the key if it is already there (like if we ran this once before) 

      # insert the key expect True  = Success
      self.assertEqual(keys.import_key('test_keyx', 'test_key desc', 
                                       'C3C3C3C3C3C3C3C33C3C3C3C3C3C3C3C', 'DES'), True)
      k = keys.get_key('test_keyx')
      self.assertEqual(k.get_value(), 'C3C3C3C3C3C3C3C33C3C3C3C3C3C3C3C')    
      # try a new insert duplicate should be false slightly different valud (starts with D3)
      self.assertEqual(keys.import_key('test_keyx', 'test_key desc', 
                                       'D3D3C3C3C3C3C3C33C3C3C3C3C3C3C3C', 'DES'),  False)
      # get it again should still be starting with C3
      k2 =  keys.get_key('test_keyx')
      self.assertEqual(k2.get_value(), 'C3C3C3C3C3C3C3C33C3C3C3C3C3C3C3C')    

  def test_DES(self):
    for tc_number in self.crypto_cases['tests']['DES_BASIC']:
      tc = self.crypto_cases['tests']['DES_BASIC'][tc_number]
      res = self.my_crypto.do_DES(tc['operation'], tc["key_name"], tc['mode'], tc['data'], tc['IV'])
      expected_result = tc["expected_result"]
      self.assertEqual(res.upper(), expected_result.upper())
  def test_EMV(self):
    # test the UDK derivation
    tc = self.crypto_cases['tests']['EMV']['UDK']
    res = self.my_crypto.do_udk(tc['key_name'], tc['PAN'], tc['PSN'])
    self.assertEqual(res.upper(), tc['expected_result'].upper())
    # test the session key
    tc = self.crypto_cases['tests']['EMV']['SESSION_KEY']
    res = self.my_crypto.do_session_key(tc['key_name'], 
                                        tc['PAN'], tc['PSN'], tc['ATC'])
    self.assertEqual(res.upper(), tc['expected_result'].upper())
    # test the arqc
    tc = self.crypto_cases['tests']['EMV']['ARQC']
    res = self.my_crypto.do_arqc(tc['key_name'], 
                        tc['PAN'], tc['PSN'], tc['ATC'], tc['data'], True)
    self.assertEqual(res.upper(), tc['expected_result'].upper())
    # test the arpc
    tc = self.crypto_cases['tests']['EMV']['ARPC']
    res = self.my_crypto.do_arpc(tc['key_name'], 
                        tc['PAN'], tc['PSN'], tc['ATC'], tc['ARQC'], tc['CSU'])
    self.assertEqual(res.upper(), tc['expected_result'].upper())


  def test_get_key_value(self):
    res = self.my_crypto.get_key_value('k3')
    self.assertEqual(res, '42c1bee22e409f96e93d7e117393172a')
    res = self.my_crypto.get_key_value('C1C1C1C11C1C1C1C')
    self.assertEqual(res, 'C1C1C1C11C1C1C1C')
    keys = self.my_crypto.get_PnCryptoKeys()
    k = keys.import_ephemeral_key('C2C2C2C22C2C2C2C', 'DES')
    res = self.my_crypto.get_key_value(k)
    self.assertEqual(res, 'C2C2C2C22C2C2C2C')
    
  def test_copy_keys(self):
    json_keys = self.my_crypto.get_PnCryptoKeys()
    for k in json_keys.keys:
      key_obj = json_keys.get_key(k)
      id =   key_obj.get_id()
      description = key_obj.get_description()
      value = key_obj.get_value()
      type = key_obj.get_type()
      mysql_keys = self.my_crypto_mysql.get_PnCryptoKeys()
      mysql_keys.delete_key(id)
      mysql_keys.import_key(id, description, value, type)
       
     
  @classmethod
  def tearDownClass(cls):
      cls.log.info("in tear down")


#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  unittest.main()

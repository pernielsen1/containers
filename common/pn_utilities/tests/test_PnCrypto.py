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

  def setUp(self):
      self.log = PnLogger.PnLogger()
      self.log.info("setUp completed starting tests")
      self.my_crypto = PnCrypto.PnCrypto()
      self.my_keys = self.my_crypto.get_PnCryptoKeys()
      with open("test_PnCrypto.json", 'r') as file:
        self.crypto_cases = json.loads(file.read())    


  def test_get_key(self):
      k = self.my_keys.get_key("k3")
      self.assertEqual(k.get_id(), 'k3')
      self.assertEqual(k.get_value(), '42c1bee22e409f96e93d7e117393172a')
      self.assertEqual(k.get_type(), 'a type')
      self.assertEqual(self.my_keys.get_key('Unknown key'), None)
      k1 = self.my_keys.get_key("DES_k1")
      


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
    
  def tearDown(self):
      self.log.info("in tear down")


#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  unittest.main()

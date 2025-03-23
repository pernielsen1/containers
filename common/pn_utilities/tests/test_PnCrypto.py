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
      self.assertEqual(k.get_name(), 'k3')
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

  def tearDown(self):
      self.log.info("in tear down")


#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  unittest.main()

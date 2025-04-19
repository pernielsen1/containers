#-----------------------------------------------------
# articles on the test patterns
#-----------------------------------------------------

import unittest
import json
import pn_utilities.logger.PnLogger as PnLogger
log = PnLogger.PnLogger()
from datetime import datetime

#-------------------------------------------------------------------
# 
#-------------------------------------------------------------------
class TestFastApi(unittest.TestCase):

  @classmethod
  def setUpClass(cls):
      with open("test_sockets.json", 'r') as file:
        cls.test_cases = json.loads(file.read())    

  def run_tests(self, segment):
    for tc_name in self.test_cases[segment]:
       test_case = self.test_cases[segment][tc_name]
       server_url = self.test_cases['server'] + ":" + test_case['port']
       num_repeats = test_case['num_repeats']
#       test_msg = test_case['msg']
       log.info("testing:" + test_case['description'] + " repeat:" + str(num_repeats) + " on server:" + server_url)
       expected_result = test_case['expected_result']
       for _ in range(num_repeats):
           self.assertEqual(200, expected_result)   
    return
  
  def test_basic(self):
    self.run_tests('SEGMENT1')

  @classmethod
  def tearDownClass(cls):
      log.info("in tear down")


#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  unittest.main()

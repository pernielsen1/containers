#-----------------------------------------------------
# articles on the test patterns
# https://docs.python.org/3/library/unittest.html
#-----------------------------------------------------


import unittest
import json
import requests
import pn_utilities.logger.PnLogger as PnLogger
log = PnLogger.PnLogger()
from datetime import datetime

#-------------------------------------------------------------------
# 
#-------------------------------------------------------------------
class TestFastApi(unittest.TestCase):

  @classmethod
  def setUpClass(cls):
      with open("test_fastapi.json", 'r') as file:
        cls.test_cases = json.loads(file.read())    

  def run_test(self, segment, test_case_name):

    test_case = self.test_cases[segment][test_case_name]
    server_url = self.test_cases['server'] + ":" + test_case['port']

    num_repeats = test_case['num_repeats']
    expected_status_code = test_case['expected_status_code']

    post_url = "http://" + server_url + "/" + test_case['path']   
    test_msg = test_case['msg']
    log.info(test_msg)
    log.info("testing:" + test_case['description'] + " repeat:" + str(num_repeats))

    for _ in range(num_repeats):
        start = datetime.now()
        str_start = datetime.strftime(start, "%H:%M:%S.%f")
        json_msg = json.dumps(test_msg)
        try:
            if test_case['method'] == 'post':
                response = requests.post(post_url, json=json_msg)
            if test_case['method'] == 'get':
                response = requests.get(post_url, json=json_msg)
            if test_case['method'] == 'delete':
                response = requests.delete(post_url, json=json_msg)
            if test_case['method'] == 'put':
                response = requests.put(post_url, json=json_msg)
            if test_case['method'] == 'patch':
                response = requests.patch(post_url, json=json_msg)
        except:
            # TODO - print the error request
            log.error("error in request post")
            return
        end = datetime.now()
        str_end = datetime.strftime(end, "%H:%M:%S.%f")
        diff = end - start
        log.info("start:" + str_start + " end:" + str_end + 
            " diff:" + str(diff) + " port:" + test_case['port'] + 
            " status:'" + str(response.status_code))
        
        self.assertEqual(response.status_code, expected_status_code)   
        # should we peek at the data ? 
        expected_json = test_case.get('expected_json', None)
        if (expected_json != None):
           return_json = response.json()
           for key, expected_val in expected_json.items():
              ret_val= return_json[key].upper()
              self.assertEqual(ret_val, expected_val)   

        try:
            log.info(response.json())
        except:
            log.error("exception occurred during json parse response was:", response)


  def test_crypto(self):
    self.run_test("EMV", "ARQC")
    self.run_test("EMV", "ARPC")

#  def test_iso(self):
#    self.run_test("tests", "0002")
#    self.run_test("tests", "0001")

  def test_key_operations(self):
    self.run_test("EMV", "KEYS")
    self.run_test("EMV", "KEY")

    self.run_test("EMV", "KEY_DELETE")
    self.run_test("EMV", "KEY_POST")
    self.run_test("EMV", "KEY_POST_DUPLICATE")   # force duplicate key
    print("key put")
    self.run_test("EMV", "KEY_PUT")     
    self.run_test("EMV", "KEY_ERROR_NOT_FOUND")     

    self.run_test("EMV", "KEY_POST_BAD")   # force pydantic error   


  @classmethod
  def tearDownClass(cls):
      log.info("in tear down")


#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  unittest.main()

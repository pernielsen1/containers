#-----------------------------------------------------
# articles on the test patterns
#-----------------------------------------------------

import unittest
import socket
import json
import pn_utilities.logger.PnLogger as PnLogger
log = PnLogger.PnLogger()
from datetime import datetime

   

#-------------------------------------------------------------------
# 
#-------------------------------------------------------------------
class TestTcpServer(unittest.TestCase):

  @classmethod
  def setUpClass(cls):
      with open("test_config.json", 'r') as file:
        cls.test_cases = json.loads(file.read())    
      cls.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
      port = cls.test_cases['port']
      server = cls.test_cases['server']
      log.info("In setup connecting to server:" + server + " on port:" + str(port))
      # s.connect((HOST, PORT))
      cls.server_socket.connect((server, port))

  def run_tests(self, segment):
    for tc_name in self.test_cases[segment]:
      test_case = self.test_cases[segment][tc_name]
      server_url = self.test_cases['server'] + ":" + test_case['port']
      num_repeats = test_case['num_repeats']
#       test_msg = test_case['msg']
      log.info("testing:" + test_case['description'] + " repeat:" + str(num_repeats) + " on server:" + server_url)
      expected_result = test_case['expected_result']
      for _ in range(num_repeats):
        data = test_case['message']['data']
        data_bytes = data.encode("utf-8")
        data_len = len(data_bytes)
        data_len_str = f"{data_len:04d}"
        self.server_socket.sendall(data_len_str.encode("utf-8"))
        self.server_socket.sendall(data_bytes)
        len_field = self.server_socket.recv(4)
        len_int = int(len_field)
        return_data = self.server_socket.recv(len_int)
        log.info("received:" + str(return_data))

        self.assertEqual(200, expected_result)   
    return
  
  def test_basic(self):
    self.run_tests('SEGMENT1')

  @classmethod
  def tearDownClass(cls):
      cls.server_socket.close()
      log.info("in tear down")


#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  unittest.main()

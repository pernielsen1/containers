#-----------------------------------------------------
# - setting up a current directory of "up one level" - we are in the "tests" sub directory
import unittest
import sys, os
import logging
import requests
import threading
import json
import time

up_one_level = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
print("appending " + up_one_level + " to sys path")
sys.path.append(up_one_level)

from communication_app import Message, CommunicationApplication   
from crypto_filters import FilterCryptoRequest, FilterCryptoResponse
from simulator_filters import FilterSimulatorBackendResponse
from iso8583_utils import Iso8583Utils
from sendmsg import CommAppCommand
#-------------------------------------------------------------------
# 
#-------------------------------------------------------------------
class TestCryptoFilters(unittest.TestCase):
    
  @classmethod
  def run_crypto_server_app(cls):
    cls.crypto_server_app.start()
 
  @classmethod
  def wait_crypto_server_ready(cls):
    logging.debug("waiting for crypto server to be ready")
    num_attempts  = 10
    attempt_no = 0
    ready = False
    while not ready and attempt_no < num_attempts:
      ping_res = cls.crypto_command.run_command(command="ping")
      if ping_res['OK']:
        logging.debug("OK ping is now reponding see if all are ready")
        ready_res = cls.crypto_command.run_command(command="ready")   
        if ready_res['OK']:
          logging.debug(str(ready_res))
          ready = ready_res['result']['return_data']['ready']      
      time.sleep(1)

  @classmethod
  def setUpClass(cls):
    logging.getLogger().setLevel(logging.DEBUG)
    cls.client_app = CommunicationApplication("config/client.json")
    cls.middle_app = CommunicationApplication("config/middle.json")
    cls.backend_app = CommunicationApplication("config/backend.json")
    cls.filter_crypto_request = FilterCryptoRequest(cls.middle_app, "FilterCryptoRequest")
    cls.filter_crypto_response = FilterCryptoResponse(cls.middle_app, "FilterCryptoResponse")
    cls.filter_simulator_backend_response = FilterSimulatorBackendResponse(cls.backend_app, "FilterSimulatorBackendResponse")
    cls.filter_simulator_request = cls.client_app.filters["FilterSimulatorTestRequest"]
    cls.filter_simulator_answer =  cls.client_app.filters["FilterSimulatorTestAnswer"]
    # iso8583_utils has logic for building test cases defined in iso8583_utils.json
    cls.iso8583_utils = Iso8583Utils(up_one_level + "/iso8583_utils.json")
    config_file = up_one_level + '/config/crypto_server.json'
                                                              
    logging.info("setup Starting the crypto server in seperate thread")
    cls.crypto_command = CommAppCommand(config_file=config_file)
    cls.crypto_server_app = CommunicationApplication(config_file)
    # reduce the time_out before starting
    cls.crypto_server_app.time_out = 3
    cls.crypto_server_thread = threading.Thread(target=cls.run_crypto_server_app)
    cls.crypto_server_thread.daemon = True
    cls.crypto_server_thread.start()
    # wait to ensure the crypto server is ready
    cls.wait_crypto_server_ready()
    logging.info("end of setup let the games begin")

      
  #---------------------------------------
  # test_arqc_arpc ... the test arpc and arqc calcualtions
  #------------------------------
  def test_arqc_arpc(self):
      test_iso_message = Message(self.iso8583_utils.build_iso_msg('test_case_1', True))
      result1 = self.filter_crypto_request.run(test_iso_message)
      print(f'result1 {result1.get_data()}')

      result2 = self.filter_crypto_response.run(result1)
      print(f'result2 {result2.get_data()}')
  
  #----------------------------------------------------------
  #  test_simulator:
  #-----------------------------------------------------------
  def wait_response_thread(self, test_iso_request:Message, expect_result:bool):
    logging.debug(f"1: test_iso_request {test_iso_request.get_data()}")
    result = self.filter_simulator_request.run(test_iso_request)
    logging.debug(f"2: after wait test completed with result: {result.get_string()}")
    result_dict = json.loads(result.get_string())
    out_message = result_dict['out_message']
    if (expect_result):
      self.assertTrue(out_message != None)
    else:
      self.assertTrue(out_message == None)

    return

  def test_simulator_arpc(self):
      test_case_1_request = Message(self.iso8583_utils.build_iso_msg('test_case_1', True))
      wait_thread = threading.Thread(target = self.wait_response_thread, args = (test_case_1_request, True))
      wait_thread.start()
      logging.debug("receiving the request messaage created in wait thread")
      request_message = self.client_app.queues['to_middle'].get(timeout=30)

      # send an answer which will wake up the waiting thread.
      test_iso_answer = self.filter_simulator_backend_response.run(request_message)
      logging.debug(f"Sending reply waking up the waking thread {test_iso_answer.get_data()}")
      test_iso_reply = self.filter_simulator_answer.run(test_iso_answer)
      wait_thread.join()
      # new case where we will not send a reply i.e. let it time out. expect time out = False
      test_case_2_request = Message(self.iso8583_utils.build_iso_msg('test_case_2', True))
      wait_thread = threading.Thread(target = self.wait_response_thread, args = (test_case_2_request, False ))
      wait_thread.start()
      logging.debug("receiving the request messaage 2 created in wait thread")
      # wait for the thread which will send the message to the to_middle queue when everything is ready
      request_message = self.client_app.queues['to_middle'].get(timeout=30)
      wait_thread.join()

  @classmethod
  def tearDownClass(cls):
      logging.info("tearing down stopping crypto server thread")
      cls.crypto_server_app.stop()
      logging.info("Joining crypto_server_thread")
      cls.crypto_server_thread.join()
      logging.info("All done")

#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  unittest.main()

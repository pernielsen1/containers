#-----------------------------------------------------
# - setting up a current directory of "up one level" - we are in the "tests" sub directory
import unittest
import sys, os
import logging
import threading
import json
import iso8583

up_one_level = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
print("appending " + up_one_level + " to sys path")
sys.path.append(up_one_level)
from communication_app import Message, Filter, CommunicationApplication   
from iso_spec import test_spec
from crypto_filters import utils, FilterCryptoRequest, FilterCryptoResponse
from simulator_filters import FilterSimulatorTestAnswer, FilterSimulatorTestRequest, FilterSimulatorBackendResponse



#-------------------------------------------------------------------
# 
#-------------------------------------------------------------------
class TestCryptoFilters(unittest.TestCase):
  @classmethod
  def run_crypto_server_app(cls):
    cls.crypto_server_app.start()
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
                                                              
    logging.info("setup Starting the crypto server in seperate thread")
    # TBD - move these cases to tests also for sendmsg .. utility
    test_case_file = up_one_level + "/sendmsg.json"
    with open(test_case_file, 'r') as f:
      cls.test_cases = json.load(f)
 
    config_file = up_one_level + '/config/crypto_server.json'
    cls.crypto_server_app = CommunicationApplication(config_file)
    cls.crypto_server_thread = threading.Thread(target=cls.run_crypto_server_app)
    cls.crypto_server_thread.daemon = True
    cls.crypto_server_thread.start()
    logging.info("end of setup let the games begin")

  def build_iso_msg(self, test_case_name):
    tc = self.test_cases['tests'].get(test_case_name, None)
    if (tc == None):
        raise ValueError(f'testcase {test_case_name} not found')
    # still here good to go
    iso_message =tc['iso_message']
    message_id = tc['message_id']
    f47_dict = utils.add_item_create_dict(iso_message['47'],'message_id', message_id)
    iso_message['47'] = json.dumps(f47_dict)
    iso_message_raw, encoded = iso8583.encode(iso_message, test_spec)
    return iso_message_raw  # bytes
      
  #---------------------------------------
  # test_arqc_arpc ... the test arpc and arqc calcualtions
  #------------------------------
  def Xest_arqc_arpc(self):
    #  self.assertTrue('FOO'.isupper())
    #  self.assertFalse('Foo'.isupper())
      test_iso_message = Message(self.build_iso_msg(test_case_name='test_case_1'))
      result1 = self.filter_crypto_request.run(test_iso_message)
      print(f'result1 {result1.get_data()}')

      result2 = self.filter_crypto_response.run(result1)
      print(f'result2 {result2.get_data()}')
  
  #----------------------------------------------------------
  #  test_simulator:
  #-----------------------------------------------------------
  def wait_response_thread(self, test_iso_request:Message, expect_result:bool):
    logging.debug(f"1: test_iso_request {test_iso_request}")
    result = self.filter_simulator_request.run(test_iso_request)
    logging.debug(f"after wait test completed with result: {result.get_string()}")
    result_dict = json.loads(result.get_string())
    out_message = result_dict['out_message']
    if (expect_result):
      self.assertTrue(out_message != None)
    else:
      self.assertTrue(out_message == None)

    return

  def test_simulator_arpc(self):
      test_case_1_request = Message(self.build_iso_msg(test_case_name='test_case_1'))
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
      test_case_2_request = Message(self.build_iso_msg(test_case_name='test_case_2'))
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

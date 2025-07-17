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


def build_iso_message(test_case_name:str):
    test_case_file = "sendmsg.json"
    if not os.path.isabs(test_case_file):
            test_case_file = os.path.join(os.getcwd(), test_case_file)
    with open(test_case_file, 'r') as f:
            test_cases = json.load(f)
    tc = test_cases['tests'].get(test_case_name, None)
    if (tc == None):
        raise ValueError(f'testcase {test_case_name} not found in {test_case_file}')
    # still here good to go
    iso_message =tc['iso_message']
    try:
        iso_message_raw, encoded = iso8583.encode(iso_message, test_spec)

        print(iso_message_raw)
        return iso_message_raw  # bytes
    except Exception as e:
        raise Exception(e)


#-------------------------------------------------------------------
# 
#-------------------------------------------------------------------
class TestCryptoFilters(unittest.TestCase):
  @classmethod
  def run_crypto_server_app(cls)
    cls.crypto_server_app.start()
  @classmethod
  def setUpClass(cls):
    logging.info("setup Starting the crypto server in seperate thread")
    # TBD - move these cases to tests also for sendmsg .. utility
    test_case_file = up_one_level + "/sendmsgjson"
    with open(test_case_file, 'r') as f:
      cls.test_cases = json.load(f)
 
    config_file = up_one_level + '/config/crypto_server.json'
    cls.crypto_server_app = CommunicationApplication(config_file)
    cls.server_thread = threading.Thread(target=cls.run_crypto_server_app)
    cls.server_thread.daemon = True
    cls.server_thread.start()
    logging.info("end of setup let the games begin")

  def build_iso_msg(self, test_case_name):
    tc = self.test_cases['tests'].get(test_case_name, None)
    if (tc == None):
        raise ValueError(f'testcase {test_case_name} not found in {test_case_file}')
    # still here good to go
    iso_message =tc['iso_message']
    iso_message_raw, encoded = iso8583.encode(iso_message, test_spec)
    print(iso_message_raw)
    return iso_message_raw  # bytes


    test_iso_message = Message(build_iso_message(test_case_name='test_case_1'))
    msg_data = test_iso_message.get_data()
    decoded, encoded = iso8583.decode(msg_data, test_spec)
    f47_dict = utils.add_item_create_dict(decoded['47'],'message_id', 123)
    decoded['47'] = json.dumps(f47_dict)
    iso_test_raw, encoded = iso8583.encode(decoded, test_spec)
    test_iso_message = Message(iso_test_raw)        
    result = filter_crypto_request.run(test_iso_message)
    # make a reply
    decoded, encoded = iso8583.decode(result.get_data(), test_spec)
    decoded['39'] = '00'  # approved
    test_iso_reply_raw, encoded = iso8583.encode(decoded, test_spec)
    test_iso_reply = Message(test_iso_reply_raw)
    print("running another test case via request to crypto server")
    result = filter_crypto_response.run(test_iso_reply)
    print(f"result of responset {result.get_data()}")


  @classmethod
  def tearDownClass(cls):
      cls.log.info("in tear down")


#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  unittest.main()

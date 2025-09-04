#-----------------------------------------------------
# - setting up a current directory of "up one level" - we are in the "tests" sub directory
import unittest
import sys, os
import logging
import threading
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
class TestCommApp(unittest.TestCase):
    
  @classmethod
  def run_grand_mama(cls):
    cls.grand_mama_app.start()
 
  @classmethod
  def wait_grand_mama_ready(cls):
     if not cls.grand_mama_command.wait_connected(is_connected=True, max_secs=10):
        raise ValueError("Grand_mama did not reply to ping in time")
     if not cls.grand_mama_command.wait_ready(max_secs=10):
        raise ValueError("Grand_mama did not become ready in time")

  @classmethod
  def setUpClass(cls):
    logging.getLogger().setLevel(logging.DEBUG)
    
    cls.grand_mama_app = CommunicationApplication("config/grand_mama.json")
    config_file = up_one_level + '/config/crypto_server.json'
                                                              
    logging.info("getting the command object")
    cls.grand_mama_command = CommAppCommand(config_file=config_file)
                                                              
    logging.info("setup Starting grand_mama in seperate thread")
    # reduce the time_out before starting
    #    cls.crypto_server_app.time_out = 3
    cls.grand_mama_thread = threading.Thread(target=cls.run_grand_mama)
    cls.grand_mama_thread.daemon = True
    cls.grand_mama_thread.start()
    # wait to ensure the crypto server is ready
    cls.wait_grand_mama_ready()
    logging.info("end of setup let the games begin")

      
  #---------------------------------------
  # test_arqc_arpc ... the test arpc and arqc calcualtions
  #------------------------------
  def test_teardown(self):
      logging.debug("Waiting a bit and then stopping")
      time.sleep(10)
      logging.debug("ready to tear down")

  @classmethod
  def tearDownClass(cls):
      logging.info("tearing down grand_mama")
      cls.grand_mama_app.stop()
      cls.grand_mama_thread.join()
      logging.info("All done")

#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  unittest.main()

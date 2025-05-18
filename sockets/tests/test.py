#-----------------------------------------------------
# needed are
# pip install redis
# https://dev.to/chanh_le/setting-up-redis-as-a-message-queue-a-step-by-step-guide-5gj0
#-----------------------------------------------------
import os
import sys
import json
import time
import pn_utilities.logger.PnLogger as PnLogger
#--------------------------------------------------------------
# so we need to cheat a little and add the socket_queues directory to path
# to find the redis_qyeye manage obj - ...
abspath = os.path.abspath(__file__)
dname = os.path.dirname(abspath)
os.chdir(dname)
sys.path.insert(0, '../socket_queues')
dname = os.path.dirname(abspath) 
#--------------------------------------------------------
from queue_manager import QueueManager
from queue_manager_factory import create_queue_manager
from message import Message, CommandMessage

log = PnLogger.PnLogger()
log.setlevel(20)  # 10 = debug, 20 = info

class TestClass():
  def __init__(self, config_file="TEST.json"):
    log.info("loading config file:" + config_file + " in dir:" + os.getcwd())
    with open(config_file, 'r') as file:
      self.config = json.loads(file.read())
    log.info("using create_queuemanager")
    self.QM = create_queue_manager(config_dict = self.config)
    self.to_queue = self.config['to_queue']
    self.filter_stat = self.config['filter_stat']


  def send(self, wait_str, num_messages, burst_size, sleep_burst_millisecs, delay_millisecs):
    log.info(f'Running: {wait_str} {num_messages} in {burst_size} with wait {burst_wait} between burst and message_wait {message_wait}')
    log.info("Resetting filter stats in " + self.filter_stat + " before start and sends test messages to queue:" + self.to_queue)
    my_message_filter = CommandMessage('filter_stat', reset='yes', key='the_key')
    self.QM.queue_send(self.filter_stat,my_message_filter.get_json())
    self.QM.queue_send('WORKER2',my_message_filter.get_json())
    
    # TBD put all queues to  reset in the json.

    msg = Message('run')
    for i in range(num_messages): 
      if (wait_str == 'wait'):
        self.QM.send_and_wait(self.to_queue, i, 'run') 
      else:
        self.QM.queue_send(self.to_queue, msg.get_json(), i) 
        
      # wait after message ? 
      if (delay_millisecs > 0):
        time.sleep(delay_millisecs/1000)
      # wait after burst
      if (i % burst_size == 0 and i > 0):
        log.info("processed " + str(i) + " messages")
      if (sleep_burst_millisecs > 0):
        time.sleep(sleep_burst_millisecs / 1000)

    log.info("for stats run the stats.sh command")


#--------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  wait_str = 'nowait'
  num_messages = 1
  burst_size = 100
  burst_wait = 0
  message_wait = 0
#  ./test.sh nowait 201 0 100 0 
 
  if (len(sys.argv) == 6):
    wait_str = sys.argv[1]
    num_messages = int(sys.argv[2])
    message_wait = int(sys.argv[3]) 
    burst_size = int(sys.argv[4])
    burst_wait = int(sys.argv[5])
  else:
    log.info("No args passed usage test.py num_messages message_wait burst_size burst_wait")

  my_test_class = TestClass()
  my_test_class.send(wait_str, num_messages, burst_size, burst_wait, message_wait) 

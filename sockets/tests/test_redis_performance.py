#-----------------------------------------------------
# needed are
# pip install redis
# https://dev.to/chanh_le/setting-up-redis-as-a-message-queue-a-step-by-step-guide-5gj0
#-----------------------------------------------------
import os
import sys
import time
# om threading import Thread  
import pn_utilities.logger.PnLogger as PnLogger
#--------------------------------------------------------------
# so we need to cheat a little and add the socket_queues directory to path
# to find the redis_qyeye manage obj - ... 
sys.path.insert(0, '../socket_queues')
#--------------------------------------------------------
 
from redis_queue_manager import RedisQueueManager
from message import Message, CommandMessage

log = PnLogger.PnLogger()
log.get_logger().level  = 20  # 10 = debug, 20 = info

redis_password = 'pn_password'
my_RQM =  RedisQueueManager(host='localhost', port=6479, password =  redis_password)


def send(wait_str, num_messages, burst_size, sleep_burst_millisecs, delay_millisecs):
    msg = Message('run')
    for i in range(num_messages): 
      if (wait_str == 'wait'):
        my_RQM.send_and_wait('to_crypto', i, 'run') 
      else:
        my_RQM.queue_send('to_crypto', msg.get_json(), i) 
        

      # wait after message ? 
      if (delay_millisecs > 0):
        time.sleep(delay_millisecs/1000)
      # wait after burst
      if (i % burst_size == 0 and i > 0):
         log.info("processed " + str(i) + " messages")
         if (sleep_burst_millisecs > 0):
           time.sleep(sleep_burst_millisecs / 1000)


#--------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  os.chdir(sys.path[0])
  wait_str = 'wait'
  num_messages = 201
  burst_size = 100
  burst_wait = 0
  message_wait = 0
#  ./run_redis_performance.sh 16000 0 100 0 runs in 112 seconds with two queue workers  = 142 per sec. doens't really help with three
#  print(sys.argv)
  if (len(sys.argv) == 6):
    wait_str = sys.argv[1]
    num_messages = int(sys.argv[2])
    message_wait = int(sys.argv[3]) 
    burst_size = int(sys.argv[4])
    burst_wait = int(sys.argv[5])
  else:
    print("No args passed usage test_redis_performance num_messages message_wait burst_size burst_wait")

# ./run_redis_performance.sh nowait 6000 0 100 0
  log.info(f'Running: {wait_str} {num_messages} in {burst_size} with wait {burst_wait} between burst and message_wait {message_wait}')
           

  if (wait_str != 'wait'):
    log.info("Resetting filter stats before start")
    my_message_filter = CommandMessage('filter_stat', reset='yes', key='the_key')
    my_RQM.queue_send('crypto_async',my_message_filter.get_json())
    my_RQM.queue_send('crypto_async2',my_message_filter.get_json())

  send(wait_str, num_messages, burst_size, burst_wait, message_wait) 

  log.info("Get your stats using the stats.sh command")
            
#  my_message = CommandMessage('stat', reset='no', key='the_key')
# my_RQM.queue_send('crypto',my_message.get_json())
#  my_RQM.queue_send('crypto',my_message_filter.get_json())
#
#  my_RQM.queue_send('crypto2',my_message.get_json())
#  my_RQM.queue_send('crypto3',my_message.get_json())
#  my_RQM.queue_send('crypto_async',my_message.get_json())

  
#-----------------------------------------------------
# needed are
# pip install redis
# https://dev.to/chanh_le/setting-up-redis-as-a-message-queue-a-step-by-step-guide-5gj0
#-----------------------------------------------------
import os
import sys
import redis
import json
import time
from threading import Thread  
import pn_utilities.logger.PnLogger as PnLogger

#--------------------------------------------------------------
# so we need to cheat a little and add the socket_queues directory to path
# to find the redis_qyeye manage obj - ... 
sys.path.insert(0, '../socket_queues')
#--------------------------------------------------------
from message import Message
 
from redis_queue_manager import RedisQueueManager

log = PnLogger.PnLogger()
log.get_logger().level  = 20  # 10 = debug, 20 = info

redis_password = 'pn_password'
my_RQM =  RedisQueueManager(host='localhost', port=6479, password =  redis_password)
redis_obj = redis.Redis(host='localhost', port=6379, db=0, password=redis_password)



def send_receive():
  MILLISECS_TO_EXPIRE = 50  # 50 = half a second
  # ro= redis.Redis(host='localhost', port=6379, password=redis_password)

  print("setting msg_id ready" + str(1042))
  redis_obj.set("another_key", "here is the messagE")
  redis_obj.set(str(1042), "1042 message no expire", px=MILLISECS_TO_EXPIRE)
  redis_obj.set(str(1942), "1043 message expires", px=MILLISECS_TO_EXPIRE)


def wait_msg(pubsub, key_to_wait_for):
    subscribe_msg = "__keyspace@0__:" + "reply_" + key_to_wait_for
    pubsub.psubscribe(subscribe_msg)
    timeout = 20
    stop_time = time.time() + timeout
    while time.time() < stop_time:
      message = pubsub.get_message(timeout=stop_time - time.time())
      if (message):
        log.debug("got message" + str(message))
        data = message['data']
        if (data == b'set'):
            return
      else:
        log.debug("did not get message ?")

    log.error("Timed out for:" + key_to_wait_for)

def send_and_wait(ro, pubsub, msg_no, msg, delay_millisecs):
    
    wait_thread = Thread(target=wait_msg, args=[pubsub, str(msg_no)])
    wait_thread.start()  
    my_message = Message(msg)
    my_RQM.queue_send('to_crypto',my_message.get_json(), msg_no)
    wait_thread.join()
    # now the data is available
    data = ro.get("reply_" + str(msg_no))
    log.debug("received data:" + str(data))
    if (delay_millisecs > 0):
       time.sleep(delay_millisecs/1000)

def go_send_and_wait(num_messages, sleep_burst_millisecs, delay_millisecs):
    pubsub = redis_obj.pubsub(ignore_subscribe_messages=True)
    for i in range(num_messages): 
      send_and_wait(redis_obj, pubsub, i, 'run', delay_millisecs) 
      if (i % 100 == 0 and i > 0):
         log.info("processed " + str(i) + " messages")
         if (sleep_burst_millisecs > 0):
           time.sleep(sleep_burst_millisecs / 1000)

#--------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  os.chdir(sys.path[0])
  # send_receive()
  go_send_and_wait(5000, 0, 30)
  my_message = Message('stat')
  my_RQM.queue_send('crypto',my_message.get_json())
  my_RQM.queue_send('crypto2',my_message.get_json())
  my_RQM.queue_send('crypto3',my_message.get_json())

  # go()
  # go_threading()
  
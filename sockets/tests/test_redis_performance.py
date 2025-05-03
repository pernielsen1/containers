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
from redis import StrictRedis
import pn_utilities.logger.PnLogger as PnLogger
message_no = 0
redis_password = 'pn_password'
log = PnLogger.PnLogger()

redis_obj = redis.Redis(host='localhost', port=6379, db=0, password=redis_password)

def send_to_queue(redis, msg_id, command):
      to_queue = 'to_crypto'
      send_msg={}
      send_msg['msg_id'] = msg_id
      send_msg['start_time'] = int(time.time() * 1000)
      send_msg['send_data'] = "here_we_go"
      send_msg['command'] = command 

      data = json.dumps(send_msg).encode('utf-8')
      log.debug("sending msg-id" + msg_id + " to queue:" + to_queue + " data:" + str(data))
      redis.hset(msg_id, "data", data)
      redis.expire(msg_id, 3600)
      redis.lpush(to_queue, msg_id)
      return msg_id

def go():
  num_msg=5
 # setup connection to redis
  for i in range(num_msg): 
    send_to_queue(redis_obj, i, 'run') 
  
  send_to_queue(redis_obj, i + 1, 'print')



def send_receive():
  MILLISECS_TO_EXPIRE = 50  # 50 = half a second
  ro= StrictRedis(host='localhost', port=6379, password=redis_password)

  print("setting msg_id ready" + str(1042))
  ro.set("another_key", "here is the messagE")
  ro.set(str(1042), "1042 message no expire", px=MILLISECS_TO_EXPIRE)
  ro.set(str(1942), "1043 message expires", px=MILLISECS_TO_EXPIRE)

 # ro.set(str(1042), "here is the messagE")
 # ro.set("another_key", "here is the messagE")
 # ro.set("another_key", "here is the messagE")
 # send_to_queue(redis_obj, message_no + 1, 'print')


#  send_to_queue(redis_obj, 1042, "run and wait")
# import asyncio

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

def send_and_wait(ro, pubsub, msg_id, message):
    
    wait_thread = Thread(target=wait_msg, args=[pubsub, msg_id])
    wait_thread.start()  
    send_to_queue(ro, msg_id, message)
    wait_thread.join()
    # now the data is available
    data = ro.get("reply_" + msg_id)
    log.debug("received data:" + str(data))

def go_send_and_wait(num_messages):
    ro= StrictRedis(host='localhost', port=6379, password=redis_password)
    pubsub = ro.pubsub(ignore_subscribe_messages=True)
    for i in range(num_messages): 
      send_and_wait(ro, pubsub, str(i), 'run') 
      if (i % 100 == 0):
         log.info("processed:" + str(i) + " messages")

    send_to_queue(redis_obj, str(i + 1), 'print')


#--------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  os.chdir(sys.path[0])
  send_receive()
  go_send_and_wait(2000)
  # go()
  # go_threading()
  
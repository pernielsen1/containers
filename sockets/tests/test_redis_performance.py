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
import threading

import pn_utilities.logger.PnLogger as PnLogger
message_no = 0
redis_password = 'pn_password'
log = PnLogger.PnLogger()

redis_obj = redis.Redis(host='localhost', port=6379, db=0, password=redis_password)

def send_to_queue(redis, send_id, command):
      to_queue = 'to_crypto'
      msg_id = str(send_id)
      send_msg={}
      send_msg['start_time'] = int(time.time() * 1000)
      send_msg['send_data'] = "here_we_go"
      send_msg['command'] = command 

      data = json.dumps(send_msg).encode('utf-8')
      log.info("sending msg-id" + msg_id + " to queue:" + to_queue + " data:" + str(data))
      redis.hset(msg_id, "data", data)
      redis.expire(msg_id, 3600)
      redis.lpush(to_queue, msg_id)

def go():
  num_msg=5000
 # setup connection to redis
  for i in range(num_msg): 
    send_to_queue(redis_obj, i, 'run') 
  
  send_to_queue(redis_obj, i + 1, 'print')

# import time
def go_threading():
  n=3
  threading.Timer(1/n, do_task).start()
  print ("Sleeping")

  time.sleep(60)
  send_to_queue(redis_obj, message_no + 1, 'print')

def do_task():
  send_to_queue(redis_obj, message_no + 1, 'run')


#--------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  os.chdir(sys.path[0])
  # go()
  go_threading()
  
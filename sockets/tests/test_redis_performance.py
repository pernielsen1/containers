#-----------------------------------------------------
# needed are
# pip install redis
# https://dev.to/chanh_le/setting-up-redis-as-a-message-queue-a-step-by-step-guide-5gj0
#-----------------------------------------------------
import os
import sys
import redis

import pn_utilities.logger.PnLogger as PnLogger
log = PnLogger.PnLogger()

def send_to_queue(redis, send_id):
      to_queue = 'to_crypto'
      msg_id = str(send_id) 
      data = b'here we go'
      log.info("sending msg-id" + msg_id + " to queue:" + to_queue + " data:" + str(data))
      redis.hset(msg_id, "data", data)
      redis.expire(msg_id, 3600)
      redis.lpush(to_queue, msg_id)

def go():
  num_msg=300
 # setup connection to redis
  redis_password = 'pn_password'
  redis_obj = redis.Redis(host='localhost', port=6379, db=0, password=redis_password)
  for i in range(num_msg): 
    send_to_queue(redis_obj, i) 

#--------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  os.chdir(sys.path[0])
  go()
  
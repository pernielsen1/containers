#-----------------------------------------------------
# needed are
# pip install redis
# https://dev.to/chanh_le/setting-up-redis-as-a-message-queue-a-step-by-step-guide-5gj0
#-----------------------------------------------------
import os
import sys
import unittest
import redis
import json
import pn_utilities.logger.PnLogger as PnLogger
log = PnLogger.PnLogger()
from datetime import datetime

   

#-------------------------------------------------------------------
# 
#-------------------------------------------------------------------
class TestRedis(unittest.TestCase):

  @classmethod
  def setUpClass(cls):
      with open("test_config.json", 'r') as file:
        cls.test_cases = json.loads(file.read())    

      # setup connection to redis
      redis_password = cls.test_cases['redis_password']
      cls.redis = redis.Redis(host='localhost', port=6379, db=0, password=redis_password)

  def run_redis_tests(self, segment):
    for tc_name in self.test_cases[segment]:
      test_case = self.test_cases[segment][tc_name]
      queue_name = test_case['queue_name']
      role = test_case['role']
      log.info("testing:" + test_case['description'] + " queue:" + queue_name + "role:" + role)
      if (role == "producer"): 
        test_meta = test_case['message_metadata']
        test_msg = test_case['message']
        ttl = test_case['ttl']
    
        self.redis.lpush(queue_name, json.dumps(test_meta))
        print(test_msg)
        self.redis.hmset(f"message:{test_meta['id']}", test_msg)
        self.redis.expire(f"message:{test_meta['id']}", ttl)

      if (role == "consumer"):
        while True:
          print("Consuming while true")
          metadata = self.redis.brpop(queue_name)
          message_info = json.loads(metadata[1].decode('utf-8'))

          # Retrieve full message details from Redis
          full_message = self.redis.hgetall(f"message:{message_info['id']}")

          print(f"Processing message ID: {message_info['id']} from sender: {message_info['sender_id']}")
          print(f"Full message details: {full_message}")
      
#        self.assertEqual(200, expected_result)   
    return
  
  def test_redis_basic(self):
    # self.run_redis_tests('REDIS')   
      test_meta =  {  
                "id": "msg123",
                "sender_id": "deviceA",
                "signal_code": "12345",  
                "criteria_index": 1
      }
      test_meta_json = json.dumps(test_meta)
      ttl = 3600
      test_msg = "Hello redis here is testing"
      queue_name="x"  
      msg_id = "1001"
      self.redis.lpush(queue_name, msg_id)
      self.redis.hset(msg_id, "data", test_msg)
      self.redis.expire(msg_id, ttl)
      while True:
          msg_id_tuple  = self.redis.brpop(queue_name)
          msg_id = msg_id_tuple[1]
          full_message = self.redis.hget(msg_id, "data")
          print(f"Full message details: {full_message}")
      

    
  @classmethod
  def tearDownClass(cls):
      log.info("in tear down")


#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  os.chdir(sys.path[0])
#  t  = TestRedis()
#  t.
  unittest.main()

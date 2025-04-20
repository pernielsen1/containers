#-----------------------------------------------------
# needed are
# pip install redis
#-----------------------------------------------------

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
    self.run_redis_tests('REDIS')

  @classmethod
  def tearDownClass(cls):
      log.info("in tear down")


#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  unittest.main()

import time
from redis import StrictRedis
password = "pn_password"
redis = StrictRedis(host='localhost', port=6379, password=password)

pubsub = redis.pubsub()
# pubsub.psubscribe('__keyspace@0__:*')
# pubsub.psubscribe('__key*__:*')
key_to_wait_for = "1042"
key_to_wait_for = "*"  # all
subscribe_msg = "__keyspace@0__:" + key_to_wait_for
pubsub.psubscribe(subscribe_msg)

print('Starting message loop wait just for key:' + key_to_wait_for)
while True:
    message = pubsub.get_message()
    if message:
        print(message)
    else:
        time.sleep(0.01)



#  redis_queue_manager -  
#  interfaces to redis and implements the low level queue_send amd queue_receive
import redis 
import json
import pn_utilities.logger.PnLogger as PnLogger
import time
from threading import Thread  
from message import Message
from queue_manager import QueueManager


log = PnLogger.PnLogger()

class QueueManagerRedis(QueueManager):
    def __init__(self, host='localhost', port=6379, password=None):
        log.info("Createing redis queue manager")
        log.info("host is" + str(host))
        self.redis = redis.Redis(host=host, port=port, db=0, password=password)
        self.queues_message_number = {}
        self.pubsub = self.redis.pubsub(ignore_subscribe_messages=True)

    #--------------------------------------------------------------------------
    # queue_send - low level functions can create unique message number though 
    #              obs takes string as input which is encoded to utf-8 before sending
    #--------------------------------------------------------------------------
    def queue_send(self, queue: str, data : str, message_number: int = None, ttl=3600):
        if (message_number != None): 
            message_id = str(message_number)
        else:
            if (self.queues_message_number.get(queue, None) == None):
                self.queues_message_number[queue] = 0   # first time send - initialize the 

            self.queues_message_number[queue] = self.queues_message_number[queue] + 1
            message_id = str(self.queues_message_number[queue]) 
        message_dict = json.loads(data)
        message_dict['message_id'] = message_id
        send_str = json.dumps(message_dict)
        data_utf8 = send_str.encode('utf-8')      
 
        self.redis.hset(message_id, "data", data_utf8)
        self.redis.expire(message_id, ttl)
        self.redis.lpush(queue, message_id)

    #------------------------------------------------------------------------
    # queue_receive - low level function receiving message from queue - 
    #                   obs will decode the data to utf-8
    #--------------------------------------------------------------------------
    def queue_receive(self, queue: str):
        msg_id_tuple = self.redis.brpop(queue)
        msg_id = msg_id_tuple[1]
        data_bin = self.redis.hget(msg_id, "data")
        return data_bin.decode('utf-8')


    def send_and_wait(self, queue, msg_no, msg, timeout=20):
        subscribe_msg = "__keyspace@0__:" + "reply_" + str(msg_no)
        self.pubsub.psubscribe(subscribe_msg)
        my_message = Message(msg)
        self.queue_send(queue,my_message.get_json(), msg_no)
        stop_time = time.time() + timeout
        more = True
        while time.time() < stop_time and more:
            message = self.pubsub.get_message(timeout=stop_time - time.time())
            if (message):
                log.debug("got message" + str(message))
                data = message['data']
                if (data == b'set'):
                    more = False
            else:
                log.debug("did not get message ?")
        self.pubsub.punsubscribe(subscribe_msg)
        data = self.redis.get("reply_" + str(msg_no))
        log.debug("received data:" + str(data))

    #------------------------------------------------------------------------
    # notify_reply - 
    #--------------------------------------------------------------------------
    def notify_reply(self, data: str, notify_send_ttl_milliseconds = 600):
        try:
            log.debug("parsing data:" + data)
            msg_dict = json.loads(data)
            msg_id = msg_dict.get('message_id', None)
            if (msg_id != None):
                reply_msg_id = "reply_" + msg_id 
                log.debug("Notifying msgid is ready" + msg_id + " with reply_msg_id:" + reply_msg_id)
                self.redis.set(reply_msg_id, data, px=notify_send_ttl_milliseconds)
       
        except Exception as e:
            log.error("Error parsing json in notify reply" + str(data))
            log.error(str(e))
       
#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
    my_RQM =  QueueManagerRedis(host='localhost', port=6479, password = 'pn_password')
    from message import Message
    my_message = Message('stat')
    my_RQM.queue_send('crypto',my_message.get_json())

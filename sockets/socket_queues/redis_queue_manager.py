#  redis_queue_manager -  
#  interfaces to redis and implements the low level queue_send amd queue_receive
import redis 
import json
import pn_utilities.logger.PnLogger as PnLogger

log = PnLogger.PnLogger()

class RedisQueueManager():
    def __init__(self, host='localhost', port=6379, password=None):
        self.redis = redis.Redis(host='localhost', port=6379, db=0, password=password)
        self.queues_message_number = {}

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

#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
    my_RQM =  RedisQueueManager(host='localhost', port=6479, password = 'pn_password')
    from message import Message
    my_message = Message('stat')
    my_RQM.queue_send('crypto',my_message.get_json())
#    my_message = Message('stop')
#    my_RQM.queue_send('crypto',my_message.get_json())

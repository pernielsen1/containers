#  message - defines the Message object
# 
# 
import time
import json

class Message():
    def __init__(self, payload: str):
        self.message_dict = {}
        self.message_dict['payload'] = payload
        self.message_dict['create_time_ns'] = time.time_ns() 
        self.message_dict['receive_time_ns'] = 0
        self.message_dict['send_time_ns'] = 0
        self.message_dict['message_id'] = None
        return

    def get_json(self):
        return json.dumps(self.message_dict)
    

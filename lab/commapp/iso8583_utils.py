import json
import iso8583
from iso_spec import test_spec


#-------------------------------------------------------------------------------------------------
# simulator_test_request:  Puts in a unique message ID in iso_message and starts a waiting process
#-------------------------------------------------------------------------------------------------
class Iso8583Utils():
    def __init__(self, test_case_file:str):
        with open(test_case_file, 'r') as f:
            self.test_cases = json.load(f)
 
    def build_iso_msg(self, test_case_name, override:bool = False):
        tc = self.test_cases['tests'].get(test_case_name, None)
        if (tc == None):
            raise ValueError(f'testcase {test_case_name} not found')
        # still here good to go
        iso_message =tc['iso_message']
        message_id = tc['message_id']
        f47_dict = self.add_item_create_dict(iso_message['47'],'message_id', message_id, override)
        iso_message['47'] = json.dumps(f47_dict)
        iso_message_raw, encoded = iso8583.encode(iso_message, test_spec)
        return iso_message_raw  # bytes

    def add_item_create_dict(self, json_maybe:str, item_name:str, item_value:any, override:bool = True):
        try: 
            return_dict = json.loads(json_maybe)
            if (override):   # some time you do not want to override - like an external message id
               return_dict[item_name] = item_value
            return return_dict
        except json.decoder.JSONDecodeError as e:
            return_dict={}
            if json_maybe is None:
                return return_dict
            else:
                return_dict['orig'] = json_maybe
                return_dict[item_name] = item_value
                return return_dict

    
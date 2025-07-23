import os
import logging
import json
import base64
import requests
import iso8583
import threading
from iso_spec import test_spec

from sendmsg import build_iso_message
from communication_app import Message, Filter, CommunicationApplication   

from crypto_filters import utils

#-------------------------------------------------------------------------------------------------
# simulator_test_request:  Puts in a unique message ID in iso_message and starts a waiting process
#-------------------------------------------------------------------------------------------------
class FilterSimulatorTestRequest(Filter):
    def __init__(self, app:CommunicationApplication , name:str):
        super().__init__(app, name)
        self.message_id_counter = 0        

    def run(self, message):
        data = message.get_data()
        logging.debug(f"simulator_test_request received message: {data}")
        try:
            decoded, encoded = iso8583.decode(data, test_spec)
        except Exception as e:
            # TBD what should error handling be in such a case
            logging.error("iso decode failed exiting silent !")
            return message
        self.message_id_counter += 1       
        message_id = str(self.message_id_counter) 
        # if message id set outside then don't override it. 
        f47_dict = utils.add_item_create_dict(decoded['47'],'message_id', message_id, override=False)
        decoded['47'] = json.dumps(f47_dict)
        message_id = f47_dict['message_id']   # message id may have been set out side - get the value. 
        new_iso_raw, encoded =  iso8583.encode(decoded, test_spec)
        logging.debug(f"simulator_test_request sending {new_iso_raw} and waiting for message_id: {message_id}")
        out_message = Message(new_iso_raw)
        # setup an event waiting for a response.. 
        return_event = threading.Event()
        self.data_dict[message_id]={'return_data': None, 'return_event': return_event}
        self.app.queues['to_middle'].put(out_message)
        # TBD set the wait seconds to external config value
        wait_result = return_event.wait(4)  # wait for response coming back (will be in filter below)
        logging.debug(f"after wait wait_result={wait_result} - data_dict: {self.data_dict}")
        return_data = self.data_dict[message_id]['return_data']
        if return_data == None:
            reply_data = None
        else:
            reply_data = return_data.hex()

        return_dict = {
                'message_id': message_id,
                'in_message': new_iso_raw.hex(),
                'out_message': reply_data
        }
        logging.debug(f"returning the return_dict {return_dict}")
        out_message = Message(json.dumps(return_dict))
        
        return out_message
#-------------------------------------------------------------------------------------------------------------
# simulator_test_answer. -a response have been received see if we have a field 47 indicating some one waiting
#-------------------------------------------------------------------------------------------------------------
class FilterSimulatorTestAnswer(Filter):
    def __init__(self, app:CommunicationApplication , name:str):
        super().__init__(app, name)

    def run(self, message):
        data = message.get_data()
        logging.debug(f'filter {self.name} in {self.app.name} running data{data}')
        try:
            decoded, encoded = iso8583.decode(data, test_spec)
        except Exception as e:
            # TBD what should error handling be in such a case
            logging.error("iso decode failed exiting silent !")
            return message
        field_47_json = decoded['47']
        logging.debug(f"should we wake up some event {field_47_json}")
        field_47_dict = json.loads(field_47_json)
        message_id=field_47_dict.get('message_id', None)
        if (message_id != None):
            send_filter = self.app.filters['FilterSimulatorTestRequest']
            logging.debug(f"message_id {message_id} and send_filter:{send_filter.data_dict}")
            event = send_filter.data_dict[message_id]['return_event']
            print(send_filter.data_dict)
            send_filter.data_dict[message_id]['return_data'] = data
            logging.debug("setting the event")
            event.set()
        else:
            logging.debug("No Text found i.e. no event to wake")
        
        return message # just continue without altering the message

#-------------------------------------------------------------------------------------------------------------
# FilterSimulatorBackendResponse: generate a dummy response i.e. make 0100 to 01001-------------------------------------------------------------------------------------------------------------

class FilterSimulatorBackendResponse(Filter):
    def __init__(self, app:CommunicationApplication , name:str):
        super().__init__(app, name)

    def run(self, message):
        data = message.get_data()
        logging.debug(f'filter {self.name} in {self.app.name} running data{data}')
        try:
            decoded, encoded = iso8583.decode(data, test_spec)
            decoded['t'] = '0110'
            decoded['39'] = '00'
            new_iso_raw, encoded =  iso8583.encode(decoded, test_spec)
            return Message(new_iso_raw)

        except Exception as e:
            # TBD what should error handling be in such a case
            logging.error("iso decode failed exiting silent !")
            return message
        
   
# Main function
if __name__ == "__main__":
    print("current dir" + os.getcwd())
    client_app = CommunicationApplication("config/client.json")

    logging.getLogger().setLevel(logging.DEBUG)

#    simulator_test_request = SimulatorTestRequest(client_app, 'simulator_test_request')
    simulator_test_request = client_app.filters['simulator_test_request']
    simulator_backend_answer  = FilterSimulatorBackendAnswer(client_app, 'simulator_test_request')

    test_iso_message = Message(build_iso_message(test_case_name='test_case_1'))
    t1 = threading.Thread(target=simulator_test_request.run, args=(test_iso_message,))
    t1.start()
    print("and now we answer")
    decoded, encoded = iso8583.decode(test_iso_message.get_data(), test_spec)
    decoded['39'] = '00'  # approved
    decoded['t'] = '0110'
    # pretend we actually got the manipulated message from simulator_test_request
    f47_dict = {}
    f47_dict['orig'] = decoded['47']
    message_id = str(simulator_test_request.message_id_counter)
    f47_dict['message_id'] = message_id
    decoded['47'] = json.dumps(f47_dict)
    test_iso_reply_raw, encoded = iso8583.encode(decoded, test_spec)
    test_iso_reply = Message(test_iso_reply_raw)
    result = simulator_test_answer.run(test_iso_reply)
    print("End of run")

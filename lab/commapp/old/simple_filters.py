import os
import logging
import json
import base64
import requests

from communication_app import Message, Filter, QueueObject, CommunicationApplication   

class FilterUpper(Filter):
    def __init__(self, app:CommunicationApplication , name:str):
        super().__init__(app, name)

    def run(self, message):
        if (self.app is not None):
            logging.debug(f'I am in {self.app.name}')
        logging.debug(f"upper filter received message: {message.get_json()}")
        return Message(message.get_string().upper())

# This file is part of the Communication Application example - not used anymore was better with a worker.
class FilterEcho(Filter):
    def __init__(self, app:CommunicationApplication , name:str):
        super().__init__(app, name)
        # Add the queue to the application - if not already there
        if 'to_middle' not in self.app.queues:
            logging.debug('Creating new queue to_middle')
            self.app.queues['to_middle'] = QueueObject('to_middle', self.app.config)
       
        
    def run(self, message):
        if (self.app is not None):
            logging.debug(f'I am in {self.app.name}')
        logging.debug(f"echo filter received message: {message.get_json()}")
        out_message = Message(message.get_string() + " and return")
        self.app.queues['to_middle'].put(out_message)
        return message


class FilterWebServerAnswer(Filter):
    def __init__(self, app:CommunicationApplication , name:str):
        super().__init__(app, name)

    def run(self, message):
        if (self.app is not None):
            logging.debug(f'I FilterWebServerAnswer am in {self.app.name}')
        
        input_string = message.get_string()
        output_string = "web_server_answer - replied with:" + input_string
        return Message(output_string)


#------------------------------------------------------
# makes a simple "work" command to the other party.
# data is wrapped in a base64 string to the other party
#-------------------------------------------------------
class FilterWebRequest(Filter):
    def __init__(self, app:CommunicationApplication , name:str):
        super().__init__(app, name)
        self.url = app.config['filters'][name]['url']
        self.filter_name_to_send = app.config['filters'][name]['filter_name_to_send']

    def run(self, message):
        if (self.app is not None):
            logging.debug(f'I am in {self.app.name}')
        logging.debug(f"web request filter received message: {message.get_json()}")
        text = message.get_string()
        data_base64 = base64.b64encode(text.encode('utf-8')).decode('utf-8')
        logging.debug(f'data {data_base64} filter: {self.filter_name_to_send}')
        msg = {
            "command": "work",
            "data_base64": data_base64,
            "filter_name": self.filter_name_to_send,
        }
        json_msg = json.dumps(msg)
        logging.debug(f"web request filter sending message: {json_msg}")

        try:
            response = requests.post(self.url, json=json_msg)

            if (response.status_code != 200):
                logging.error("Error: " + str(response.status_code) + " " + response.text)
                return
            # stilll here
            json_response = response.json()
            return_data_dict = json_response['return_data']
            data_base64 = return_data_dict['data_base64']
            data = base64.b64decode(data_base64)      
            return_message  =  Message(data)
            return return_message
                        
        except requests.exceptions.ConnectionError as errc:
            logging.error(f'So there was no luck with {self.url} gracefully exiting')
            logging.error("Error Connecting:",errc)

        # Maybe set up for a retry, or continue in a retry loop
        except requests.exceptions.RequestException as e:
            logging.error("will that didn't work out exiting")
            raise Exception(e)

# Main function
if __name__ == "__main__":
    print("current dir" + os.getcwd())
    logging.getLogger().setLevel(logging.DEBUG)

    filter_upper  = FilterUpper(CommunicationApplication("config/middle.json"), 'upper')
    msg = Message('Hello, World!')
    msg_upper = filter_upper.run(msg)
    print(msg_upper.get_string())

    filter_echo = FilterEcho(CommunicationApplication('config/backend.json'), 'echo')
    msg_echo = filter_echo.run(msg)
    filter_web_server_answer = FilterWebServerAnswer(CommunicationApplication('config/client.json'), 'web_server_answer')
    msg_web_server_answer = filter_web_server_answer.run(msg)
    print(msg_web_server_answer.get_string())    

    # TBD test case for this ? 

    filter_web_request = FilterWebRequest(CommunicationApplication('config/middle.json'), 'web_request')    

    print("End of simple_filters.py")   
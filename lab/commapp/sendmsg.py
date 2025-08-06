import os
import json
import requests
import sys
import base64
import logging
import time
from iso8583_utils import Iso8583Utils

server_url = 'localhost'

class CommAppCommand():
    def __init__(self, server:str = None, port:int = None, config_file:str = None):
        """ if config file is passed then server and port is taken from here else assumed passed as parms """
        if config_file != None:
            config_file_path = config_file
            if not os.path.isabs(config_file):
                config_file_path = os.path.join(os.getcwd(), config_file)
            with open(config_file_path, 'r') as f:
                config = json.load(f)
                server = config['server']
                port = config['command_port']
        self.post_url = (f"http://{server}:{port}")

    def run_command(self, command, queue_name:str=None, data:any =None, num_messages:int = 1):
        if isinstance(data, bytes) or isinstance(data, bytearray):
            is_base64 = True
            text = base64.b64encode(data).decode("ascii")
        else:  # data is already string   
            text = data
            is_base64 = False

        if (command == 'send' or command == 'work'):
            msg = {
                "command": command,
                "queue_name": queue_name,
                "is_base64": is_base64,
                "text": text,
                "data_base64": text,
                "filter_name": "FilterSimulatorTestRequest",
                "num_messages": num_messages    
            }
        else: 
            msg = {
                "command": command,
            }
        
        json_msg = json.dumps(msg)
        try:
            response = requests.post(self.post_url, json=json_msg)
            if (response.status_code != 200):
                return {"OK": False, "connected": True, "error": str(response.status_code) + " " + response.text}
            else: 
                return {"OK": True, "connected": True, "result": response.json()}
                
        except requests.exceptions.ConnectionError as errc:
            return {"OK": False, "connected": False, "error:": f"So there was no luck with {self.post_url} gracefully exiting"}
        except requests.exceptions.RequestException as e:
            logging.debug("Well that didn't work" + str(e))  
            raise

    def wait_connected(self, is_connected:bool, max_secs:int):
        num_secs = 0
        while num_secs <= max_secs:   # at least one attempt
            result = self.run_command(command='ping')
            if is_connected and result['connected'] == True:
                return True
            if not is_connected and result['connected'] == False:
                return True
            time.sleep(1)
            num_secs = num_secs + 1
        
        return False # still here means we did not receive expected result in time

    def wait_ready(self, max_secs:int):
        num_secs = 0
        while num_secs <= max_secs:   # at least one attempt
            result = self.run_command(command='ready')
            print(result)
            if result['OK']:
                if result['result']['return_data']['ready']:
                    return True
            time.sleep(1)
            num_secs = num_secs + 1
      
        return False  # still here means we have not gotten a ready signal
#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    port = 8077
    num_messages  = 1
    data = None
    queue_name = 'to_middle'
    server = 'localhost'
    command = 'test'
    if (len(sys.argv) > 1):
        port = int(sys.argv[1])
        command = sys.argv[2]
    command_server = CommAppCommand(server=server, port=port)

    if (command == 'send' or command == 'test'):
        if (len(sys.argv) > 3):
            queue_name = sys.argv[3]
            data = sys.argv[4]
            if len(sys.argv) > 5: 
                num_messages = int(sys.argv[5])

    if command == 'test':
        command = 'work'
        iso8583_utils = Iso8583Utils("iso8583_utils.json")
        data = iso8583_utils.build_iso_msg(test_case_name='test_case_1')
        result= command_server.run_command(command=command, queue_name=queue_name, data=data, num_messages=num_messages)
    logging.debug(f"running command{command}, queue_name:{queue_name} data:{data} num_message:{num_messages}")
    result=command_server.run_command(command=command, queue_name=queue_name, data=data, num_messages=num_messages)
    logging.debug(f"result was {result}")

# curl http://localhost:8009
#{"received": "ok", "hello": "world"}
#curl --data "{\"this\":\"is a test\"}" --header "Content-Type: application/json" http://localhost:8009
# {"this": "is a test", "received": "ok"}

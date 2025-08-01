import os
import json
import requests
import sys
import base64
from datetime import datetime
from iso8583_utils import Iso8583Utils

server_url = 'localhost'

# time.strftime(format[, t])¶

def do_stat(json_response):
    NANO_TO_SECONDS = 1000000000
    return_data_str = json_response['return_data']
    return_data_threads = json.loads(json.loads(return_data_str))

    for thread_stat in return_data_threads:
#        print(thread_stat)
        first_ns  = thread_stat['first_ns']
        last_ns  = thread_stat['last_ns']
        elapsed = last_ns - first_ns 
        num_measurements = thread_stat['num_measurements']
        if num_measurements == 0:
            average_sec = 0 
        else:
            average_sec = (elapsed / num_measurements)/ NANO_TO_SECONDS
          
        name  = thread_stat['name']
        first_ns_str = datetime.fromtimestamp(first_ns/NANO_TO_SECONDS).strftime('%H:%M:%S.%f')
        last_ns_str = datetime.fromtimestamp(last_ns/NANO_TO_SECONDS).strftime('%H:%M:%S.%f')
#        average_sec_str  = 
        print(f'{name} start {first_ns_str} end {last_ns_str} {num_measurements} elapsed:{elapsed/NANO_TO_SECONDS:.2f} average per sec: {average_sec:.4f}' )

    print("after")

#-----------------------------------------------
def send_request(port, command, queue_name:str=None, data:any =None, num_messages:int = 1):
    post_url = "http://" + server_url + ":" + str(port) 
    is_base64 = False
    if isinstance(data, bytes) or isinstance(data, bytearray):
        is_base64 = True
        text = base64.b64encode(data).decode("ascii")
    else:  # text is already string   
        text = data

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
    print(json_msg)
    try:
        response = requests.post(post_url, json=json_msg)
    
        print(response)
        if (response.status_code != 200):
            print("Error: " + str(response.status_code) + " " + response.text)
            return
        # stilll here
        if (command == 'stat'): 
            do_stat(response.json())
        else:
            print(response.json())
    except requests.exceptions.ConnectionError as errc:
           print(f'So there was no luck with {post_url} gracefully exiting')
           print ("Error Connecting:",errc)
       
    # Maybe set up for a retry, or continue in a retry loop
    except requests.exceptions.RequestException as e:
        print("will that didn't work out exiting")
        raise Exception(e)


 
#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
    num_messages  = None
    text = None
    queue_name = None
    command = 'test'

    if (len(sys.argv) > 1):
        port = int(sys.argv[1])
        command = sys.argv[2]

    print(command)    
    if (command == 'send' or command == 'test'):
        queue_name = sys.argv[3]
        text = sys.argv[4]
        if len(sys.argv) > 5: 
            num_messages = int(sys.argv[5])
    else:
        send_request(port, command)


    if command == 'test':
        iso8583_utils = Iso8583Utils("iso8583_utils.json")
        iso_msg_raw = iso8583_utils.build_iso_msg(test_case_name='test_case_1')
        send_request(port, "work", queue_name, iso_msg_raw, num_messages)

# curl http://localhost:8009
#{"received": "ok", "hello": "world"}

#curl --data "{\"this\":\"is a test\"}" --header "Content-Type: application/json" http://localhost:8009
# {"this": "is a test", "received": "ok"}

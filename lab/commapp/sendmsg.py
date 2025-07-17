import os
import json
import requests
import sys
import base64
from datetime import datetime
import iso8583
from iso_spec import test_spec

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
            "filter_name": "simulator_test_request",
            "num_messages": num_messages    
        }
    else: 
        msg = {
            "command": command,
        }
    
    json_msg = json.dumps(msg)
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

def build_iso_message(test_case_name:str):
    test_case_file = "sendmsg.json"
    if not os.path.isabs(test_case_file):
            test_case_file = os.path.join(os.getcwd(), test_case_file)
    with open(test_case_file, 'r') as f:
            test_cases = json.load(f)
    tc = test_cases['tests'].get(test_case_name, None)
    if (tc == None):
        raise ValueError(f'testcase {test_case_name} not found in {test_case_file}')
    # still here good to go
    iso_message =tc['iso_message']
    try:
        iso_message_raw, encoded = iso8583.encode(iso_message, test_spec)

        print(iso_message_raw)
        return iso_message_raw  # bytes
    except Exception as e:
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
        
    if (command == 'send' or command == 'test'):
        queue_name = sys.argv[3]
        text = sys.argv[4]
        if len(sys.argv) > 5: 
            num_messages = int(sys.argv[5])
    if command != 'test':
        send_request(port, command, queue_name, text, num_messages)
    if command == 'test':
        iso_msg_raw = build_iso_message(test_case_name='test_case_1')
#        send_request(port, "send", queue_name, iso_msg_raw, num_messages)
        send_request(port, "work", queue_name, iso_msg_raw, num_messages)

# curl http://localhost:8009
#{"received": "ok", "hello": "world"}

#curl --data "{\"this\":\"is a test\"}" --header "Content-Type: application/json" http://localhost:8009
# {"this": "is a test", "received": "ok"}

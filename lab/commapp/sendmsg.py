
import json
import requests
import sys
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
        print(f'{name} start_ns: {first_ns} elapsed:{elapsed} average per sec: {average_sec}' )

    print("after")

#-----------------------------------------------
def send_request(port, command, queue_name=None, text=None):
    post_url = "http://" + server_url + ":" + str(port) 
    if (command == 'send'):
        msg = {
            "command": command,
            "queue_name": queue_name,
            "text": text    
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
    
#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
    text = None
    queue_name = None
    port = int(sys.argv[1])
    command = sys.argv[2]
    if (command == 'send'):
        queue_name = sys.argv[3]
        text = sys.argv[4]
        print(sys.argv)
    send_request(port, command, queue_name, text)


# curl http://localhost:8009
#{"received": "ok", "hello": "world"}

#curl --data "{\"this\":\"is a test\"}" --header "Content-Type: application/json" http://localhost:8009
# {"this": "is a test", "received": "ok"}


import json
import requests
import sys
server_url = 'localhost'

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
    response = requests.post(post_url, json=json_msg)
    print(response)
    if (response.status_code != 200):
        print("Error: " + str(response.status_code) + " " + response.text)
        return
    # stilll here
    print(response.json())


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


import json
import requests
import sys
server_url = 'localhost'

#-----------------------------------------------
def send_request(port, text):
    post_url = "http://" + server_url + ":" + str(port) 
    msg = {
        "cmd": "send", 
        "text": text                              
    }
    json_msg = json.dumps(msg)
    response = requests.post(post_url, json=json_msg)
    print(response)
    print(response.json())


#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
    port = int(sys.argv[1])
    text = sys.argv[2]
    send_request(port, text)
 
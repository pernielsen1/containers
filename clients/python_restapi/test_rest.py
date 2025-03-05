# select virtual env python_restapi  (ctrl-shift-p)
from datetime import datetime
import requests
import json
import os
import sys
sys.path.append(os.getcwd() + '/test_rest/server')
print("current dir:" + os.getcwd())
print(sys.path)


config_dir = ''
config_file = 'test_rest.json'
#-----------------------------------------------------------------------------------------
# load config ... load the test_rest.json who has the test cases and connection details.
#-----------------------------------------------------------------------------------------
def load_config():
    with open(config_dir +  config_file, 'r') as file:
        json_data = file.read()
        return json.loads(json_data)
#-----------------------------------------------------------------------------------------
# do_it : load config - and run a test case with the name test_case_name
#-----------------------------------------------------------------------------------------
def run_test(test_case_name):
    config = load_config()

    test_case = config['tests'][test_case_name]
    server_url = config['server'] + ":" + test_case['port']

    num_repeats = test_case['num_repeats']

    post_url = "http://" + server_url + "/" + test_case['path']   
    test_msg = test_case['msg']
    print(test_msg)
    print("testing:" + test_case['description'] + " repeat:" + str(num_repeats))
 
    for _ in range(num_repeats):
        start = datetime.now()
        str_start = datetime.strftime(start, "%H:%M:%S.%f")
        json_msg = json.dumps(test_msg)
        response = requests.post(post_url, json=json_msg)
        end = datetime.now()
        str_end = datetime.strftime(end, "%H:%M:%S.%f")
        diff = end - start
        print("start:" + str_start + " end:" + str_end + 
            " diff:" + str(diff) + " port:" + test_case['port'])
        print(response.json())
    

# here we go
if __name__ == '__main__':

    run_test("0001")
    run_test("0002")




# api_url = "http://127.0.0.1:5000/countries"
    # response = requests.get(api_url)
    # print(response.json())
    # test_url = "http://127.0.0.1:5000/tests"
    # response = requests.get(test_url)
    # print(response.json())
    #    post_url = "http://127.0.0.1:5000/transcode_0100"
    #    msg = {
    #        "msg_code": "0100",
    #        "f002": "1234567890123456",
    #        "f004": "000000012345",
    #        "f049": "752"
    #    }

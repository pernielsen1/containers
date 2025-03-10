# select virtual env python_restapi  (ctrl-shift-p)
from datetime import datetime
import requests
import json
import os
import sys
import logging
import pn_utilities.PnLogger as PnLogger

#... this is for the virtual env - still needed ? 20250308 check it
sys.path.append(os.getcwd() + '/test_rest/server')
print("current dir:" + os.getcwd())
print(sys.path)

#-----------------------------------------------------------------------------
#
#-----------------------------------------------------------------------------
import logging

log = None

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
        try:
            response = requests.post(post_url, json=json_msg)
        except:
            # TODO - print the error request
            print("error in request.post")
            return
        end = datetime.now()
        str_end = datetime.strftime(end, "%H:%M:%S.%f")
        diff = end - start
        print("start:" + str_start + " end:" + str_end + 
            " diff:" + str(diff) + " port:" + test_case['port'])
        try:
            print(response.json())
        except:
            print("exception occurred during json parse response was:", response)


#-----------------------------------------------------------------
# init_logging():  set up the logging
# https://stackoverflow.com/questions/14058453/making-python-loggers-output-all-messages-to-stdout-in-addition-to-log-file
#------------------------------------------------------------------
def init_logging(level = logging.INFO):
    name = Path(__file__).stem
    
    global log
    log = logging.getLogger(name)
    log.setLevel(level)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    fh = logging.FileHandler(name + ".log")
    fh.setLevel(level)
    fh.setFormatter(formatter)

    log.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(formatter)
    log.addHandler(ch)

#--------------------------------------------------------
# the main routine
#--------------------------------------------------------
    
def main():
    mylogger = PnLogger.PnLogger(level=logging.INFO)
    mylogger.info("x")
    init_logging()
    log.info('Started')
    run_test("0002")
    run_test("0001")

    log.info('Finished')

# here we go
if __name__ == '__main__':
    main()




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

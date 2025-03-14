# select virtual env python_restapi  (ctrl-shift-p)
from datetime import datetime
import requests
import json
import os
import sys
import logging
import pn_utilities.PnLogger as PnLogger

#... this is for the virtual env - still needed ? 20250308 check it
# sys.path.append(os.getcwd() + '/test_rest/server')
# print("current dir:" + os.getcwd())
# print(sys.path)
# Nope 20230312 doesn't seem to be needed

#-----------------------------------------------------------------------------
#
#-----------------------------------------------------------------------------
# import logging

log = None       # the global logging object - currently init in main process
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
    log.info(test_msg)
    log.info("testing:" + test_case['description'] + " repeat:" + str(num_repeats))
 
    for _ in range(num_repeats):
        start = datetime.now()
        str_start = datetime.strftime(start, "%H:%M:%S.%f")
        json_msg = json.dumps(test_msg)
        try:
            response = requests.post(post_url, json=json_msg)
        except:
            # TODO - print the error request
            log.error("error in request.post")
            return
        end = datetime.now()
        str_end = datetime.strftime(end, "%H:%M:%S.%f")
        diff = end - start
        log.info("start:" + str_start + " end:" + str_end + 
            " diff:" + str(diff) + " port:" + test_case['port'])
        try:
            log.info(response.json())
        except:
            log.error("exception occurred during json parse response was:", response)


#--------------------------------------------------------
# the main routine
#--------------------------------------------------------
    
def main():
    global log
    log = PnLogger.PnLogger(level=logging.INFO)
    log.info('Started')
    run_test("0002")
    run_test("0001")

    log.info('Finished')

# here we go
if __name__ == '__main__':
    main()

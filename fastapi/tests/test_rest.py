# select virtual env python_restapi  (ctrl-shift-p)
from datetime import datetime
import requests
import json

#... this is for the virtual env - still needed ? 20250308 check it
# sys.path.append(os.getcwd() + '/test_rest/server')
# print("current dir:" + os.getcwd())
# print(sys.path)
# Nope 20230312 doesn't seem to be needed

#-----------------------------------------------------------------------------
#
#-----------------------------------------------------------------------------
# import logging
import pn_utilities.PnLogger as PnLogger
log = PnLogger.PnLogger()


config_dir = ''
config_file = 'test_rest.json'
#-----------------------------------------------------------------------------------------
# do_it : load config - and run a test case with the name test_case_name
#-----------------------------------------------------------------------------------------
def run_test(segment, test_case_name):
    config = load_config()

    test_case = config[segment][test_case_name]
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
            if test_case['method'] == 'post':
                response = requests.post(post_url, json=json_msg)
            if test_case['method'] == 'get':
                response = requests.get(post_url, json=json_msg)
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


#-----------------------------------------------------------------------------------------
# load config ... load the test_rest.json who has the test cases and connection details.
#-----------------------------------------------------------------------------------------
def load_config():
    with open(config_dir +  config_file, 'r') as file:
        json_data = file.read()
        return json.loads(json_data)

#--------------------------------------------------------
# the main routine
#--------------------------------------------------------
    
def main():
    log.info('Started')
    run_test("tests", "0002")
    run_test("tests", "0001")
    run_test("EMV", "ARQC")
    run_test("EMV", "ARPC")
    run_test("EMV", "KEYS")
    run_test("EMV", "KEY")

    log.info('Finished')

# here we go
if __name__ == '__main__':
    main()

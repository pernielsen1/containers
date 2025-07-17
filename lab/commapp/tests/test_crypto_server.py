import os
import json
import requests
import sys
# - this file is located in test - subdir to main - go one level up and add that directory to system path
up_one_level = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
print("appending " + up_one_level + " to sys path")
sys.path.append(up_one_level)
from communication_app import CommunicationApplication

#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':   
    print("here we go")
    os.chdir(up_one_level)
    config_file = up_one_level + '/config/crypto_server.json'
    app = CommunicationApplication(config_file)
    app.start()

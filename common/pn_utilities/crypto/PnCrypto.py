
import os
import json

DATA_DIR = '../data/'
class PnCryptKey():
    key = {}
    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)
    def __init__(self, name="", value="", type=""):
        self.key['name'] = name
        self.key['value'] = value
        self.key['type'] = type
    def get_name(self):
        return self.key['name']
    def get_value(self):
        return self.key['value']
    def get_type(self):
        return self.key['type']
    def get_key(self):
        return self.key
    
class PnCryptoKeys:
    keys = {}
    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)
    def __init__(self, config_file="", name=""):
        self.name = name
        if (config_file == ""):
            config_file = DATA_DIR + "PnCryptoKeys.json"
        with open(config_file, 'r') as file:
            dict = json.loads(file.read())    
            self.keys = dict['crypto_keys']

    def get_keys(self):
        return self.keys
    def get_key(self, key_name):
        return self.keys.get(key_name, 'Not Found')
        
    def get_name(self):
        return self.name
    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)
    #-------------------------------------------------------------
    # do_dummy
    #-------------------------------------------------------------
    def do_dummy(self):
        return "do_dummy not implemented yet"


#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  my_keys = PnCryptoKeys()
  print(my_keys.get_keys()) 
  print(my_keys.get_key('k3')) 
  print(my_keys.get_key('k3xyz')) 

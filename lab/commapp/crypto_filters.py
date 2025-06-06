import os
import logging
import json
import base64
import requests
import iso8583
from iso_spec import test_spec


from communication_app import Message, Filter, CommunicationApplication   

import pn_utilities.crypto.PnCrypto as PnCrypto

#-------------------------------------------------------------------------------
# filter_crypto_answer filter. -  answering crypto requess on the crypto_server.
# called from "work" in command app - actual request  
# input is a json string with the request 
#---------------------------------------------------------------------------------
class FilterCryptoAnswer(Filter):
    def __init__(self, app:CommunicationApplication , name:str):
        super().__init__(app, name)
        self.pn_crypto = PnCrypto.PnCrypto(self.app.config['filters'][name]['crypto_config_file'])

    def run(self, message):
        data = message.get_data()
        logging.debug(f'filter {self.name} in {self.app.name} running data{data}')
        json_string = message.get_string()
        json_dict = json.loads(json_string)
        imk = 'IMK_k1' 
        pan = json_dict['pan']
        psn = '01'
        atc = '0001'
        data = "00000000510000000000000007920000208000094917041900B49762F2390000010105A0400000200000000000000000"
        
        resp = {}
        resp['arqc'] = self.pn_crypto.do_arqc(imk, pan, psn, atc, data, True)
        resp['text'] = json_dict['text'] + " with a lot of crypto" 
        return Message(json.dumps(resp))

#------------------------------------------------------
# makes a simple "work" command to the other party.
# data is wrapped in a base64 string to the other party
#-------------------------------------------------------
class FilterCryptoRequest(Filter):
    def __init__(self, app:CommunicationApplication , name:str):
        super().__init__(app, name)
        self.url = app.config['filters'][name]['url']
        self.filter_name_to_send = app.config['filters'][name]['filter_name_to_send']

    def run(self, message):
        data = message.get_data()
        logging.debug(f'CryptoRequest processing {data.hex()}')
        try:
            decoded, encoded = iso8583.decode(data, test_spec)
        except Exception as e:
            # TBD what should error handling be in such a case
            logging.error("iso decode failed exiting silent !")
            return message
             
        input_dict = { "imk" : "IMK_k1", "pan": "5656781234567891", "psn": "01", "atc": "0001",
                      "data" : "00000000510000000000000007920000208000094917041900B49762F2390000010105A0400000200000000000000000"}
        input_dict['pan'] = decoded['2']
        input_dict['text'] = decoded['47']
        input_dict_as_json_bytes = json.dumps(input_dict).encode('ascii')
        data_base64 = base64.b64encode(input_dict_as_json_bytes).decode('ascii')
        logging.debug(f'data {data_base64} filter: {self.filter_name_to_send}')
        msg = {
            "command": "work",
            "data_base64": data_base64,
            "filter_name": self.filter_name_to_send,
        }
        json_msg = json.dumps(msg)
        logging.debug(f"web request filter sending message: {json_msg}")

        try:
            response = requests.post(self.url, json=json_msg)

            if (response.status_code != 200):
                logging.error("Error: " + str(response.status_code) + " " + response.text)
                return
            # stilll here
            json_response = response.json()
            return_data_dict = json_response['return_data']
            data_base64 = return_data_dict['data_base64']
            data = base64.b64decode(data_base64)      
            return Message(data)
                        
        except requests.exceptions.ConnectionError as errc:
            logging.error(f'So there was no luck with {self.url} gracefully exiting')
            logging.error("Error Connecting:",errc)

        # Maybe set up for a retry, or continue in a retry loop
        except requests.exceptions.RequestException as e:
            logging.error("will that didn't work out exiting")
            raise Exception(e)

# Main function
if __name__ == "__main__":
    print("current dir" + os.getcwd())
    client_app = CommunicationApplication("config/client.json")
    middle_app = CommunicationApplication("config/middle.json")

    logging.getLogger().setLevel(logging.DEBUG)

    filter_crypto_answer = FilterCryptoAnswer(client_app, "crypto_answer")
    filter_crypto_request = FilterCryptoRequest(middle_app, "crypto_request")
    message = Message("A dummy message")
    from sendmsg import build_iso_message
    print("running answer locally")
    test_iso_message = Message(build_iso_message(test_case_name='test_case_1'))
#    result = filter_crypto_answer.run(test_iso_message)
#    print(result.get_data())
    print("running via request to crypto server")
    result = filter_crypto_request.run(test_iso_message)
    print(result.get_data())
    print("running another test case via request to crypto server")
    test_iso_message_2 = Message(build_iso_message(test_case_name='test_case_2'))
    result = filter_crypto_request.run(test_iso_message_2)
    print(result.get_data())
    

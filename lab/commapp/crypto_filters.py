import os
import logging
import json
import base64
import requests
import iso8583
from iso_spec import test_spec

from sendmsg import build_iso_message
from communication_app import Message, Filter, CommunicationApplication   

import pn_utilities.crypto.PnCrypto as PnCrypto

class utils:
    # convert a base64 str to a bytes and then to string
    @staticmethod
    def base64_to_str(base64_str:str, encoding = 'ascii'):
        return base64.b64decode(base64_str).decode(encoding)
    # convert a string to bytes and then to base64 as ascii string
    @staticmethod
    def str_to_base64(s:str, encoding = 'ascii'):
        return base64.b64encode(s.encode(encoding)).decode('ascii')
        
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
        resp = {}
        what = json_dict['what']
        if what == 'arqc': 
            data = "00000000510000000000000007920000208000094917041900B49762F2390000010105A0400000200000000000000000"
            resp['arqc'] = self.pn_crypto.do_arqc(imk, pan, psn, atc, data, True)
            resp['text'] = json_dict['text'] + " arqc with a lot of crypto" 

        if what == 'arpc':
            arqc = json_dict['arqc']
            csu = json_dict['csu']
            resp['arpc'] = self.pn_crypto.do_arqc(imk, pan, psn, atc, arqc, csu)
            resp['text'] = json_dict['text'] + " arpc with a reponse a lot of crypto" 
            
        return Message(json.dumps(resp))

#---------------------------------------------------------
# FilterCryptoRequest - is inbound i.e. handle the 0100
# makes a simple "work" command to the other party.
# data is wrapped in a base64 string to the other party
#---------------------------------------------------------
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
        input_dict['what'] = 'arqc'
        input_dict['pan'] = decoded['2']
        input_dict['text'] = decoded['47']
        data_base64 = utils.str_to_base64(json.dumps(input_dict))
        logging.debug(f'data {data_base64} filter: {self.filter_name_to_send}')
        msg = {
            "command": "work",
            "data_base64": data_base64,
            "filter_name": self.filter_name_to_send,
        }

        try:
            response = requests.post(self.url, json=json.dumps(msg))
            if (response.status_code != 200):
                logging.error("Error: " + str(response.status_code) + " " + response.text)
                return
            # stilll here place the response (return_data. data_base64 in field 47
            json_response = response.json()
            decoded['47'] = utils.base64_to_str(json_response['return_data']['data_base64'])
            new_iso_raw, encoded =  iso8583.encode(decoded, test_spec)
            return Message(new_iso_raw)
                        
        except requests.exceptions.ConnectionError as errc:
            logging.error(f'So there was no luck with {self.url} gracefully exiting')
            logging.error("Error Connecting:",errc)
        # Maybe set up for a retry, or continue in a retry loop
        except requests.exceptions.RequestException as e:
            logging.error("Well that didn't work out exiting")
            raise Exception(e)

#--------------------------------------------------------------------------------------------
# FilterCryptoResponse - is outbound handle the 0110 - the field 47 have the inboudn arqc.
# data is wrapped in a base64 string to the other party
#-------------------------------------------------------------------------------------------
class FilterCryptoResponse(Filter):
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
        input_dict['what'] = 'arpc'
        input_dict['pan'] = decoded['2']
        input_dict['csu'] = "00" # TBD on basis of 39
        field_47_json = decoded['47']
        field_47_dict = json.loads(field_47_json)
        input_dict['arqc'] = field_47_dict['arqc']
        input_dict['text'] = decoded['47']

        data_base64 = utils.str_to_base64(json.dumps(input_dict))
        logging.debug(f'data {data_base64} filter: {self.filter_name_to_send}')
        msg = {
            "command": "work",
            "data_base64": data_base64,
            "filter_name": self.filter_name_to_send,
        }

        try:
            response = requests.post(self.url, json=json.dumps(msg))
            if (response.status_code != 200):
                logging.error("Error: " + str(response.status_code) + " " + response.text)
                return
            # stilll here
            json_response = response.json()
            decoded['47'] = utils.base64_to_str(json_response['return_data']['data_base64'])

            new_iso_raw, encoded =  iso8583.encode(decoded, test_spec)
            return Message(new_iso_raw)



        except requests.exceptions.ConnectionError as errc:
            logging.error(f'So there was no luck with {self.url} gracefully exiting')
            logging.error("Error Connecting:",errc)

        # Maybe set up for a retry, or continue in a retry loop
        except requests.exceptions.RequestException as e:
            logging.error("Well that didn't work out exiting")
            raise Exception(e)


# Main function
if __name__ == "__main__":
    print("current dir" + os.getcwd())
    client_app = CommunicationApplication("config/client.json")
    middle_app = CommunicationApplication("config/middle.json")

    logging.getLogger().setLevel(logging.DEBUG)

    filter_crypto_answer = FilterCryptoAnswer(client_app, "crypto_answer")
    filter_crypto_request = FilterCryptoRequest(middle_app, "crypto_request")
    filter_crypto_response = FilterCryptoResponse(middle_app, "crypto_response")

    test_iso_message = Message(build_iso_message(test_case_name='test_case_1'))
    result = filter_crypto_request.run(test_iso_message)
    # make a reply
    decoded, encoded = iso8583.decode(result.get_data(), test_spec)
    decoded['39'] = '00'  # approved
    test_iso_reply_raw, encoded = iso8583.encode(decoded, test_spec)
    test_iso_reply = Message(test_iso_reply_raw)
    result = filter_crypto_response.run(test_iso_reply)
    print("result of request")
    print(result.get_data())
    print("running another test case via request to crypto server")
    test_iso_message_2 = Message(build_iso_message(test_case_name='test_case_2'))
    result = filter_crypto_request.run(test_iso_message_2)
    print("result of response")
    print(result.get_data())
    

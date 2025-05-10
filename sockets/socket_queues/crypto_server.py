# ToDo - metadata what is reallly required ? 
import sys
import json
import requests

from socket_queues import SocketQueues
import pn_utilities.logger.PnLogger as PnLogger
import pn_utilities.crypto.PnCrypto as PnCrypto

log = PnLogger.PnLogger()

class CryptoServer():
    def __init__(self, config_file):
        log.info("Using config file:" + config_file)
        with open(config_file, 'r') as file:
            self.config = json.loads(file.read())
        self.my_server = SocketQueues(sys.argv[1])
        method = self.config.get("method", None)
        if (method == 'fastapi'):
            log.info("Method is fastapi")
            self.fastapi = self.config['fastapi']
            self.server_url = self.fastapi['server'] + ":" + self.fastapi['port']
            self.post_url = "http://" + self.server_url + "/" + self.fastapi['path']   
            self.test_msg = self.fastapi['msg']
            self.my_server.add_filter_func("arqc", self.arqc_fastapi, None)
        else:
            log.info("method is NOT fastapi loading local crypto")
            self.my_PnCrypto = PnCrypto.PnCrypto()
            self.my_server.add_filter_func("arqc", self.arqc, None)
   
        self.my_server.start_workers()
   
    def filter_echo(self, data, private_obj):
        s= 'echo:' + data.decode('utf-8')
        byte_arr = s.encode('utf_8')
        return byte_arr

    def arqc(self, data, private_obj):
        msg = json.loads(data)
        payload = msg['payload']
        log.debug("Payload was:" + str(payload))
        arqc_data = "00000000510000000000000007920000208000094917041900B49762F2390000010105A0400000200000000000000000"

        res = self.my_PnCrypto.do_arqc('IMK_k1','5656781234567891' , '01', '0001', arqc_data, True)
        msg['reply'] = res
        return json.dumps(msg)


    def arqc_fastapi(self, data, private_obj):
        msg = json.loads(data)
        payload = msg['payload']
        log.debug("arqc_fastapi Payload was:" + str(payload))

        json_msg = json.dumps(self.test_msg)
        log.debug("arqc_fastapi:" + str(json_msg))
        try:
            response = requests.post(self.post_url, json=json_msg)
            log.debug("got response:" + str(response))
            msg['reply'] = response.json()
            return json.dumps(msg)
        except Exception as e:
            log.error("error in request post" + str(e))
            msg['reply'] = "error"
            return json.dumps(msg)



#----------------------------
# 
# ---
# local tests
#--------------------------------
if __name__ == '__main__':
    my_crypto_server = CryptoServer(sys.argv[1])

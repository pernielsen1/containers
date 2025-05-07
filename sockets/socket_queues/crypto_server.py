# ToDo - metadata what is reallly required ? 
import sys
import json
import time
from socket_queues import SocketQueues
import pn_utilities.logger.PnLogger as PnLogger
import pn_utilities.crypto.PnCrypto as PnCrypto

log = PnLogger.PnLogger()
my_PnCrypto = PnCrypto.PnCrypto()

max_elapsed = 0
def filter_echo(data, private_obj):
    s= 'echo:' + data.decode('utf-8')
    byte_arr = s.encode('utf_8')
    return byte_arr

def arqc(data, private_obj):
    msg = json.loads(data)
    payload = msg['payload']
    log.debug("Payload was:" + str(payload))
    arqc_data = "00000000510000000000000007920000208000094917041900B49762F2390000010105A0400000200000000000000000"

    res = my_PnCrypto.do_arqc('IMK_k1','5656781234567891' , '01', '0001', arqc_data, True)
    msg['reply'] = res
    return json.dumps(msg)
#    byte_arr = json.dumps(msg).encode('utf-8')
#    return byte_arr

#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
    my_server = SocketQueues(sys.argv[1])
    my_server.add_filter_func("arqc", arqc, None)
    my_server.start_workers()
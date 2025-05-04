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
    msg = json.loads(data.decode('utf-8'))
    command = msg['command']
    log.debug("Command was:" + str(command))
    arqc_data = "00000000510000000000000007920000208000094917041900B49762F2390000010105A0400000200000000000000000"

    res = my_PnCrypto.do_arqc('IMK_k1','5656781234567891' , '01', '0001', arqc_data, True)
    end_time = int(time.time() * 1000)
    elapsed = 0
    try:
        elapsed = end_time - msg['start_time']
    except:
        log.error("Error calculating elapsed probably no start_time in input")
    global max_elapsed
    ONE_MILLION = 100000
    if (elapsed > max_elapsed):
        max_elapsed = elapsed
        in_secs = elapsed / ONE_MILLION
        log.debug("new max elapsed:" + str(max_elapsed) + " in secs " + str(in_secs))
    if (command == 'print'):
        log.info("Print command - max elapsed:" + str(max_elapsed) + "in secs:" 
                     + str(max_elapsed/ONE_MILLION))
        max_elapsed = 0
            
    msg['reply'] = res
    byte_arr = json.dumps(msg).encode('utf-8')
    return byte_arr

#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
    my_server = SocketQueues(sys.argv[1])
    my_server.add_filter_func("arqc", arqc, None)
    my_server.start_workers()
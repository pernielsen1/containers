# ToDo - metadata what is reallly required ? 
import json
from socket_queues import SocketQueues, Filter
import pn_utilities.logger.PnLogger as PnLogger
import pn_utilities.crypto.PnCrypto as PnCrypto

log = PnLogger.PnLogger()
my_PnCrypto = PnCrypto.PnCrypto()


def filter_echo(self, data, private_obj):
    s= 'echo:' + data.decode('utf-8')
    byte_arr = s.encode('utf_8')
    return byte_arr

def arqc(self, data, private_obj):
    s = data.decode('utf-8')
    msg = json.loads(s)
    command = msg['command']
    log.debug("Command was:" + str(command))
    arqc_data = "00000000510000000000000007920000208000094917041900B49762F2390000010105A0400000200000000000000000"

    res = my_PnCrypto.do_arqc('IMK_k1','5656781234567891' , '01', '0001', arqc_data, True)
    end_time = int(time.time() * 1000)
    elapsed = 0
    try:
        elapsed = end_time - msg['start_time']
    except:
        print("small error")
    global max_elapsed
    ONE_MILLION = 100000
    if (elapsed > max_elapsed):
        max_elapsed = elapsed
        in_secs = elapsed / ONE_MILLION
        log.debug("new max elapsed:" + str(max_elapsed) + " in secs " + str(in_secs))
    if (command == 'print'):
        log.info("Print command - max elapsed:" + str(max_elapsed) + "in secs:" 
                     + str(max_elapsed/ONE_MILLION))
            
    msg['reply'] = res
    s = json.dumps(msg)
    byte_arr = s.encode('utf_8')
    return byte_arr


#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
    my_server = SocketQueues(sys.argv[1])
    my_server.add_filter_func(arqc)
    my_server.start_workers()
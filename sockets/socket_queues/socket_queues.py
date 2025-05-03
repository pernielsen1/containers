# ToDo - metadata what is reallly required ? 

#--------------------------------------------------------------------------
# socket_queues:  works in two different variationss
# socket to queue bridges a socket connection to redis queue
# echo queue to queue - just the echo server mimiking the host
# config file is sent as argument 
# -------------------------------------------------------------------------
import sys
import threading
import time
import datetime
import socket
import redis
import json
import pn_utilities.logger.PnLogger as PnLogger
import pn_utilities.crypto.PnCrypto as PnCrypto

log = PnLogger.PnLogger()
my_PnCrypto = PnCrypto.PnCrypto()

max_elapsed = 0

class Filter():
    def __init__(self, name, func, private_obj=None):
        self.name = name
        self.func = func
        self.private_obj = private_obj

    def run(self, data):    
        log.debug("running filter" + self.name + " with data:" + str(data))
        return self.func(data, self.private_obj)
        
class Filters():
    def __init__(self):
        self.filters = {}
        self.filter_funcs = {}

    def add_filter(self, name, func, private_obj=None):
        self.filters[name] = Filter(name, func, private_obj)  

#-------------------------------------------------------------------
# 
#-------------------------------------------------------------------
class SocketQueues():
    # the init load the config file to dict config.
    def __init__(self, config_file="config.json"):
        self.filters = {}
        self.filter_funcs = {}
        log.info("Using config file:" + config_file)
        with open(config_file, 'r') as file:
            self.config = json.loads(file.read())
        log_level = self.config.get('log_level', None)
        if (log_level != None):
            log_obj = log.get_logger()
            log_obj.setLevel(log_level)
        
        log.info("starting:" +  self.config['name'])
        self.add_filter_func('echo', self.filter_echo)
        self.add_filter_func('arqc', self.arqc)

        # set up redis queue - used both by client & servers
        password = self.config['message_broker']['password']
        self.redis = redis.Redis(host='localhost', port=6379, db=0, password=password)
        self.start_workers()
 
    def add_filter_func(self ,name, func):
        self.filter_funcs[name] = func
#
    def establish_socket_if_needed(self, name):
        if (self.config[name]['type'] == 'socket'):
            port = self.config[name]['port']
            host = self.config[name]['host']
            if (self.config[name]['role'] == 'server'):
                log.info('Starting server on:' + host + ' on port:' + str(port))
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.bind((host, port))
                s.listen()
                conn, addr = s.accept()
                log.info('Accepted client from' + str(addr) + ' on port' + str(port))
                return conn
            else:  # establish client
                conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                conn.connect((host, port))
                log.info('established connection to:' + host + ' on port:' + str(port))
                return conn
        else:
            return None

    def create_worker(self, frm, to, frm_conn, to_conn):
        filter_name = self.config[to].get('filter', None)
        notity_send_ttl_milliseconds = self.config[to].get('notify_send_ttl_milliseconds', -1)
        name = frm + ' to ' + to
        log.info("creating worker:" + name + " filter:" + str(filter_name))
        
        if (filter_name == None):
            filter = None
        else:
            func = self.filter_funcs[filter_name]
            filter =  Filter(filter_name, func, None)

        if (self.config[frm]['type'] == 'socket' and self.config[to]['type'] == 'socket'):    
            return Worker(self, name,   rcv_conn=self.frm_conn, 
                                        snd_conn=to_conn, 
                                        filter=filter)
        if (self.config[frm]['type'] == 'socket' and self.config[to]['type'] == 'queue'):    
            return Worker(self, name,   rcv_conn=frm_conn, 
                                        snd_queue=self.config[to]['send_queue'],
                                        filter=filter)
        if (self.config[frm]['type'] == 'queue' and self.config[to]['type'] == 'socket'):    
            return Worker(self, name,   rcv_queue=self.config[frm]['recv_queue'], 
                                        snd_conn=to_conn, 
                                        filter=filter, notity_send_ttl_milliseconds = notity_send_ttl_milliseconds)  
        if (self.config[frm]['type'] == 'queue' and self.config[to]['type'] == 'queue'):    
            # send to my own send queue   TBD - this needs more description... and thinking
            return Worker(self, name, rcv_queue=self.config[frm]['recv_queue'], 
                                        snd_queue=self.config[frm]['send_queue'],
                                        filter=filter, notity_send_ttl_milliseconds = notity_send_ttl_milliseconds)  

    def start_workers(self):
        if (self.config['setup'] == 'queue_worker'):
            log.info("Establishing queue_worker")
            self.client_worker = self.create_worker('queue_worker', 'queue_worker', None, None)
            self.server_worker = None
        else: 

            log.info("establishing sockets")
            self.client_conn = self.establish_socket_if_needed('client')
            self.server_conn = self.establish_socket_if_needed('server')
            log.info("sockets established creating workers")
            self.client_worker = self.create_worker('client', 'server', self.client_conn, self.server_conn) 
            self.server_worker = self.create_worker('server', 'client', self.server_conn, self.client_conn) 

        # setup client thread and start
        self.client_worker_thread = threading.Thread(target=self.client_worker.receive_forever)
        self.client_worker_thread.daemon = True
        self.client_worker_thread.start()
        
        if (self.server_worker != None):
        # setup server thread and start
            self.server_worker_thread = threading.Thread(target=self.server_worker.receive_forever)
            self.server_worker_thread.daemon = True
            self.server_worker_thread.start()
        else:
            self.server_worker_thread = None

        self.go_controller()        
        
    def go_controller(self):
        log.info("in controller")
        while True:
            time.sleep(10)

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

#----------------------------------------------------------------------------------------------------------
# Worker: the worker object - receives from either socket or queue and forwards to either socket or queue
#----------------------------------------------------------------------------------------------------------
class Worker():
    def __init__(self, SQ_obj:SocketQueues, name:str, 
                 rcv_conn=None, rcv_queue=None, 
                 snd_conn=None, snd_queue=None, 
                 filter = None, notity_send_ttl_milliseconds=-1):
        
        self.SQ_obj = SQ_obj
        self.name  = name
        self.rcv_conn  = rcv_conn
        self.rcv_queue = rcv_queue
        self.snd_conn  = snd_conn
        self.snd_queue = snd_queue
        self.filter = filter
        self.send_id = 0
        self.id_prefix = self.SQ_obj.config['message_broker']['id_prefix']
        self.ttl = self.SQ_obj.config['message_broker']['ttl']
        self.redis = self.SQ_obj.redis
        self.notify_send_ttl_milliseconds = notity_send_ttl_milliseconds
        self.notify_send_ttl_milliseconds = notity_send_ttl_milliseconds
    def send(self, data):
        if (self.filter != None):
            log.debug("apply filter:" + self.filter.name + " on:" + str(data))
            data = self.filter.run(data)
        if (data == None):
            log.warning("Data is none ! - exiting send")
            return 0
        if (len(data) == 0):
            log.warning("len of data is zero - exiting send")
            return 0
        if (self.snd_conn != None):
            return self.send_socket(data)
        if (self.send_queue == 'debug'):
            return self.send_debug(data)
        if (self.send_queue != None):
            return self.send_queue(data)

        raise Exception("Not possible to send both conn and queue are None")
    
    def receive_forever(self):
        if (self.rcv_conn != None):
            self.receive_socket_forever()
        if (self.rcv_queue != None):
            self.receive_queue_forever()

        raise Exception("Not possible to receive_forever both receive socket and queue are None")

    #-------------------------------------------------------------
    # send_socket- send message via socket
    #-------------------------------------------------------------
    def send_socket(self, data):
        log.info("sending on socket:" + str(data))
        send_len = len(data)
        send_len_str = f"{send_len:04d}"
        self.snd_conn.sendall(send_len_str.encode("utf-8"))
        self.snd_conn.sendall(data)
        return len(data)

    #-------------------------------------------------------------
    # send_queue- send message to redis queue
    #-------------------------------------------------------------
    def send_queue(self, data):
        self.send_id = self.send_id + 1
        msg_id = self.id_prefix + str(self.send_id) 
        log.debug("sending msg-id" + msg_id + " to queue:" + self.snd_queue + " data:" + str(data))
        self.redis.hset(msg_id, "data", data)
        self.redis.expire(msg_id, self.ttl)
        self.redis.lpush(self.snd_queue, msg_id)
        if (self.notify_send_ttl_milliseconds > 0):
            try: 
                json_data = data.decode('utf-8')
                log.debug("parsing data" + json_data)
                msg_dict = json.loads(json_data)
                msg_id = msg_dict.get('msg_id', None)
                if (msg_id != None):
                    reply_msg_id = "reply_" + msg_id 
                    log.debug("Notifying msgid is ready" + msg_id + " with reply_msg_id:" + reply_msg_id)
                    self.redis.set(reply_msg_id, data, px=self.notify_send_ttl_milliseconds)
            except:
                log.error("Error parsing json in send_queue" + str(data))

        return len(data)

    #-------------------------------------------------------------
    # send_debug: log into debug instead of sending
    #-------------------------------------------------------------
    def send_debug(self, data):
        log.debug("sending to debug" + str(data))

    #---------------------------------------------------------------
    # receive_socket_forever : read message from socket and send on
    #---------------------------------------------------------------
    def receive_socket_forever(self):
        log.info("receiving from socket")
        while True:
            len_field = self.rcv_conn.recv(4)
            if (len(len_field) < 4):
                log.error("we received less than 4 time to exit")
                return
            log.debug("got len field:" + str(len_field))
            len_int = int(len_field)
            data = self.rcv_conn.recv(len_int)
            log.debug("received:" + str(data))
            # now use the send worker
            self.send(data)
    #---------------------------------------------------------------
    # receive_queue_forever : read message from queue and send on
    #---------------------------------------------------------------
    def receive_queue_forever(self):
        log.info("Receiving from:" + self.rcv_queue)
        while True:
            msg_id_tuple = self.SQ_obj.redis.brpop(self.rcv_queue)
            msg_id = msg_id_tuple[1]
            data = self.redis.hget(msg_id, "data")
            # now use the send worker
            log.debug("receive_queue sending msg_id" + str(msg_id) + " data:" + str(data))
            self.send(data)
    

#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
    my_server = SocketQueues(sys.argv[1])

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
import socket
import redis
import json
import pn_utilities.logger.PnLogger as PnLogger
from redis_queue_manager import RedisQueueManager
from message import Message, Measurements

log = PnLogger.PnLogger()

max_elapsed = 0


class Filter():
    def __init__(self, name, func, private_obj=None):
        self.name = name
        self.func = func
        self.private_obj = private_obj
        log.debug("Filter object created name" + self.name + " private object is:" +str(self.private_obj))

    def run(self, data):    
        log.debug("running filter" + self.name + " with data:" + str(data))
        return self.func(data, self.private_obj)
            
#-------------------------------------------------------------------
# SocketQueues - class brigde sockets to qeueue or vise versa...
# rename to comm bridges ? 
#-------------------------------------------------------------------
class SocketQueues():
    # the init load the config file to dict config.
    def __init__(self, config_file="config.json"):
        self.filters = {}
        self.workers = {}
        log.info("Using config file:" + config_file)
        with open(config_file, 'r') as file:
            self.config = json.loads(file.read())
        log_level = self.config.get('log_level', None)
        if (log_level != None):
            log_obj = log.get_logger()
            log_obj.setLevel(log_level)
        
        log.info("starting:" +  self.config['name'])
  
        # set up redis queue - used both by client & servers
        password = self.config['message_broker']['password']
        self.redis = redis.Redis(host='localhost', port=6379, db=0, password=password)
        self.RQM = RedisQueueManager(host=self.config['message_broker']['host'], 
                                     port = self.config['message_broker']['port'], 
                                     password = self.config['message_broker']['password']) 
         
                                     
        self.controller_queue = self.config['controller_queue']


    def add_filter_func(self ,name, func, private_obj=None):
        self.filters[name] = Filter(name, func, private_obj)
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
       
        filter = self.filters.get(filter_name, None)

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
        # create the workers from config
        if (self.config['setup'] == 'queue_worker'):
            log.info("Establishing queue_worker")
            self.workers['client_worker'] = self.create_worker('queue_worker', 'queue_worker', None, None)
        else: 
            log.info("establishing sockets")
            self.client_conn = self.establish_socket_if_needed('client')
            self.server_conn = self.establish_socket_if_needed('server')
            log.info("sockets established creating workers")
            self.workers['client_worker'] = self.create_worker('client', 'server', self.client_conn, self.server_conn) 
            self.workers['server_worker'] = self.create_worker('server', 'client', self.server_conn, self.client_conn) 

        # and start the threads
        for key in self.workers:
            self.workers[key].thread.start()

        # plus go in controller mode
        self.go_controller()        
        
    def go_controller(self):
        start_time_ns = time.time_ns() 
        log.info("Starting controller at time_ns:" + str(start_time_ns))
        while True:
            message_json = self.RQM.queue_receive(self.controller_queue)
            log.debug("Controller got:" + str(message_json))
            message_dict =  message_dict = json.loads(message_json)
            create_time_ns = message_dict['create_time_ns']
            if (create_time_ns < start_time_ns):
                log.info("Ignoring old command from time_ns" + str(create_time_ns))
            else:
                payload = message_dict['payload']
                log.debug("Received payload" + payload)
                if ( payload == 'stop'):
                    log.info("received stop - exiting here will kill deamon threads")
                    exit(0)
                    return
                if ( payload =='stat'):
                    for key in self.workers:
                        self.workers[key].measurements.print_stat(reset=True)


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
        self.thread = threading.Thread(target=self.receive_forever)
        self.thread.deamon = True
        self.measurements = Measurements(10)

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
        self.measurements.add_measurement(data)
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

        log.debug("sending " + str(data))
        if (self.notify_send_ttl_milliseconds > 0):
            log.debug("sending notification instead of to queue")
            try: 
                json_data = data
                log.debug("parsing data:" + json_data)
                msg_dict = json.loads(json_data)
                msg_id = msg_dict.get('message_id', None)
                if (msg_id != None):
                    reply_msg_id = "reply_" + msg_id 
                    log.debug("Notifying msgid is ready" + msg_id + " with reply_msg_id:" + reply_msg_id)
                    self.redis.set(reply_msg_id, data, px=self.notify_send_ttl_milliseconds)
            except Exception as e:
                log.error("Error parsing json in send_queue" + str(data))
                log.error(str(e))
        else: 
            self.SQ_obj.RQM.queue_send(self.send_queue)

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
            data = self.SQ_obj.RQM.queue_receive(self.rcv_queue)
            log.debug("receive_queue sending " + str(data))
            self.send(data)
    
#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
    my_server = SocketQueues(sys.argv[1])
    my_server.start_workers()

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
log = PnLogger.PnLogger()

                    
#-------------------------------------------------------------------
# 
#-------------------------------------------------------------------
class SocketQueues():
    # the init load the config file to dict config.
    def __init__(self, config_file="config.json"):
        log.info("Using config file" + config_file)
        with open(config_file, 'r') as file:
            self.config = json.loads(file.read())   

        # set up redis queue - used both by client & servers
        password = self.config['message_broker']['password']
        self.redis = redis.Redis(host='localhost', port=6379, db=0, password=password)
        self.start_workers()

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
        name = frm + ' to ' + to
        if (self.config[frm]['type'] == 'socket' and self.config[to]['type'] == 'socket'):    
            return Worker(self, name,   rcv_conn=self.frm_conn, 
                                        snd_conn=to_conn)
        if (self.config[frm]['type'] == 'socket' and self.config[to]['type'] == 'queue'):    
            return Worker(self, name,   rcv_conn=frm_conn, 
                                        snd_queue=self.config[to]['send_queue'])
        if (self.config[frm]['type'] == 'queue' and self.config[to]['type'] == 'socket'):    
            return Worker(self, name,   rcv_queue=self.config[frm]['recv_queue'], 
                                        snd_conn=to_conn)
        if (self.config[frm]['type'] == 'queue' and self.config[to]['type'] == 'queue'):    
            return Worker(self, name, rcv_queue=self.config[frm]['recv_queue'], 
                                        snd_queue=self.config[to]['send_queue'])

    def start_workers(self):
        log.info("establishing sockets")
        self.client_conn = self.establish_socket_if_needed('client')
        self.server_conn = self.establish_socket_if_needed('server')
        log.info("sockets established")

        self.client_worker = self.create_worker('client', 'server', self.client_conn, self.server_conn) 
        self.server_worker = self.create_worker('server', 'client', self.server_conn, self.client_conn) 
        # setup client thread and start
        self.client_worker_thread = threading.Thread(target=self.client_worker.receive_forever)
        self.client_worker_thread.daemon = True
        self.client_worker_thread.start()
        # setup server thread and start
        self.server_worker_thread = threading.Thread(target=self.server_worker.receive_forever)
        self.server_worker_thread.daemon = True
        self.server_worker_thread.start()
        self.go_controller()        
        
    def go_controller(self):
        log.info("in controller")
        while True:
            time.sleep(10)

#----------------------------------------------------------------------------------------------------------
# Worker: the worker object - receives from either socket or queue and forwards to either socket or queue
#----------------------------------------------------------------------------------------------------------
class Worker():
    def __init__(self, SQ_obj:SocketQueues, name:str, 
                 rcv_conn=None, rcv_queue=None, 
                 snd_conn=None, snd_queue=None):
        self.SQ_obj = SQ_obj
        self.name  = name
        self.rcv_conn  = rcv_conn
        self.rcv_queue = rcv_queue
        self.snd_conn  = snd_conn
        self.snd_queue = snd_queue
        self.send_id = 0
        self.id_prefix = self.SQ_obj.config['message_broker']['id_prefix']
        self.ttl = self.SQ_obj.config['message_broker']['ttl']
        self.redis = self.SQ_obj.redis

    def send(self, data):
        if (data == None):
            log.info("Data is none ! - exiting send")
            return 0
        if (len(data) == 0):
            log.info("len of data is zero - exiting send")
            return 0
        if (self.snd_conn != None): 
            return self.send_socket(data)
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
        log.info("sending msg-id" + msg_id + " to queue:" + self.snd_queue)
        self.redis.lpush(self.snd_queue, msg_id)
        self.redis.hset(msg_id, "data", data)
        self.redis.expire(msg_id, self.ttl)
        return len(data)
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
            log.info("got len field:" + str(len_field))
            len_int = int(len_field)
            data = self.rcv_conn.recv(len_int)
            log.info("received:" + str(data))
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
            log.info("receive_queue sending msg_id" + str(msg_id) + " data:" + str(data))
            self.send(data)
    
    #----------------------------------------------------
    # filter functions where we install the real workers.
    #----------------------------------------------------
    def filter_echo(self, data):
        str_response = data.decode("utf-8")
        str_response = "echo:" + str_response
        response_bytes = str_response.encode("utf-8")
        return response_bytes
#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
    my_server = SocketQueues(sys.argv[1])

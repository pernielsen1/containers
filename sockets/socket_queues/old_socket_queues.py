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
        print("config" + config_file)
        with open(config_file, 'r') as file:
            self.config = json.loads(file.read())    
        port = self.config['port']
        host = self.config['host']
        password = self.config['message_broker']['password']
        self.redis = redis.Redis(host='localhost', port=6379, db=0, password=password)

        if (self.config['role'] == "server"):
            self.go_server(host, port)  # listen for client - accept and then route socket to queue and vise versa
        if (self.config['role'] == "client"):
            self.go_client(host, port)  # connect to server - accept and then route socket to queue and vise versa
        if (self.config['role'] == "echo"):
            self.go_echo()


    def go_controller(self):
        while True:
            time.sleep(10)
        return
    
    def socket_receiver_thread(self):
        conn = self.conn
        id = 0
        queue_name = self.config['recv_to_queue']
        ttl = self.config['message_broker']['ttl']
        id_prefix = self.config['message_broker']['id_prefix']
        
        log.info("in socket_receiver")
        while True:
            len_field = conn.recv(4)
            if (len(len_field) < 4):
                log.error("we received less than 4 time to exit")
                return
            print(len_field)
            log.info("got len field:" + str(len_field))
            len_int = int(len_field)
            data = conn.recv(len_int)
            log.info("received:" + str(data))
            id = id + 1
            msg_id = id_prefix + str(id) 
            log.info("sending with msg-id" + msg_id)
            self.redis.lpush(queue_name, data)
            self.redis.hmset(f"message:{msg_id}", data)
            self.redis.expire(f"message:{msg_id}", ttl)


    #-------------------------------------------------------------------
    # queue_receiver : Read from redis queue and send via socket 
    #-------------------------------------------------------------------
    def queue_receiver_thread(self):
        conn = self.conn
        queue_name = self.config['send_from_queue']
        while True:
            metadata = self.redis.brpop(queue_name)
            message_info = json.loads(metadata[1].decode('utf-8'))
            # Retrieve full message details from Redis
            full_message = self.redis.hgetall(f"message:{message_info['id']}")
            print(f"Processing message ID: {message_info['id']} from sender: {message_info['sender_id']}")
            print(f"Full message details: {full_message}")
            send_len = len(full_message)
            send_len_str = f"{send_len:04d}"
            conn.sendall(send_len_str.encode("utf-8"))
            conn.sendall(full_message)
    #---------------------------------------------------------------------
    #
    #---------------------------------------------------------------------
    def start_socket_threads(self):
        self.recv_thread = threading.Thread(target=self.socket_receiver_thread)
        self.recv_thread.daemon = True
        self.recv_thread.start()        

        self.send_thread = threading.Thread(target=self.queue_receiver_thread)
        self.send_thread.daemon = True
        self.send_thread.start()

        # join the receiver and wait
        self.recv_thread.join()        


    def go_server(self, host, port):
       log.info('Starting server on:' + host + ' on port:' + str(port))
       with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
          s.bind((host, port))
          s.listen()
          self.conn, addr = s.accept()
          log.info('Accepted client from' + str(addr))
          self.start_socket_threads()

    def go_client(self, host, port):
        log.info("In setup connecting to server:" + host + " on port:" + str(port))
        self.conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.conn.connect((host, port))
        self.start_socket_threads()

    #-------------------------------------------------------------------
    # go_echo:  read from one queeu - dummy reply and write to another
    #-------------------------------------------------------------------
    def go_echo(self):
        id_prefix = self.config['message_broker']['id_prefix']
        ttl = self.config['message_broker']['ttl']
        send_queue_name = self.config['send_to_queue']
        receive_queue_name = self.config['receive_from_queue']
        log.info("Receiving from:" + receive_queue_name + " echoing to:" + send_queue_name)
        id = 0
        while True:
            metadata = self.redis.brpop(receive_queue_name)
            message_info = json.loads(metadata[1].decode('utf-8'))
            # Retrieve full message details from Redis
            full_message = self.redis.hgetall(f"message:{message_info['id']}")
            print(f"Processing message ID: {message_info['id']} from sender: {message_info['sender_id']}")
            print(f"Full message details: {full_message}")
            # create echo reply
            str_response = full_message.decode("utf-8")
            str_response = "echo:" + str_response
            response_bytes = str_response.encode("utf-8")
            id = id + 1
            msg_id = id_prefix + str(id) 
            log.info("sending with msg-id" + msg_id + " to queue:" + send_queue_name)
            self.redis.lpush(send_queue_name, data)
            self.redis.hmset(f"message:{msg_id}", response_bytes)
            self.redis.expire(f"message:{msg_id}", ttl)

#----------------------------------------------------------------------------------------------------------
# Worker: the worker object - receives from either socket or queue and forwards to either socket or queue
#----------------------------------------------------------------------------------------------------------
class Worker():
    def __init__(self, SQ_obj:SocketQueues, type:str, name:str, 
                 rcv_conn=None, rcv_queue=None, 
                 snd_conn=None, snd_queue=None):
        self.SQ_obj = SQ_obj
        self.type  = type
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
        if (self.snd_conn != None): 
            return self.send_socket(data)
        if (self.send_queue != None):
            return self.send_queue(data)
        raise Exception("Not possible to send both conn and queue are None")
    
    def receive_forever(self):
        if (self.rcv_conn != None):
            return self.receive_socket_forever()
        if (self.rcv_queue != None)
            return self.receive_queue_forever()
        raise Exception("Not possible to receive_forever both receive socket and queue are None")

    def send_socket(self, data):
        send_len = len(data)
        send_len_str = f"{send_len:04d}"
        self.send_socket.sendall(send_len_str.encode("utf-8"))
        self.send_socket.sendall(data)
        return len(data)
    #-------------------------------------------------------------
    # send_queue- send message to redis queue
    #-------------------------------------------------------------
    def send_queue(self, data):
        meta_data = {"id": "msg123", "sender_id": "deviceA", "signal_code": "12345",  "criteria_index": 1 }
        self.send_id = self.send_id + 1
        msg_id = self.id_prefix + str(self.send_id) 
        meta_data['id'] = msg_id
        log.info("sending msg-id" + msg_id + " to queue:" + self.snd_queue)
        self.redis.lpush(self.snd_queue, meta_data)
        self.redis.hmset(f"message:{msg_id}", data)
        self.redis.expire(f"message:{msg_id}", self.ttl)
        return len(data)

    def receive_socket_forever(self):
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

        return    
    
    def receive_queue_forever(self):
        log.info("Receiving from:" + self.rcv_queue)
        while True:
            metadata = self.SQ_obj.redis.brpop(self.rcv_queue)
            message_info = json.loads(metadata[1].decode('utf-8'))
            # Retrieve full message details from Redis
            full_message = self.redis.hgetall(f"message:{message_info['id']}")
            print(f"Processing message ID: {message_info['id']} from sender: {message_info['sender_id']}")
            print(f"Full message details: {full_message}")
            # now use the send worker
            self.send(full_message)

        return    
    
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

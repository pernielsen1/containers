This prompt comes in 3 pars

1: My new request
2: What I have done to improve.
3: The original prompt
4: The Original code after my adjustment
Good luck

1: My new request
The do_POST needs to be rewritten to 
a: accept a json structure and validate it
b: the JSON requestt should have the "name" of a queue, the "command" a string to send to the queue. It should return OK if queue found and command is valid.
Valid command are "stop", "stat", "reset"
2a: The instruaction of non blocking did not work.
I have rewritten to make a solution that works
2b: I reuse the solution with the config.json so I can start three processes.
client the "test client" playing the partner
middle the acutal application
backend a simulated backend.
config files follow:
client.json
{
    "name": "client", 
    "description": "Simulates being the client connects on 4242 and sends in test message",
    "log_level": 10,
    "BackendHostThread": true,
    "BackendHostPort": 4242,
    "ListenHostThread": false,
    "ListenHostPort": 0,
    "CommandThreadPort": 8077
}
middle.json
{
    "name": "middle", 
    "description": "The actual application connecting client and backend",
    "log_level": 10,
    "BackendHostThread": true,
    "BackendHostPort": 4243,
    "ListenHostThread": true,
    "ListenHostPort": 4242, 
    "CommandThreadPort": 8078
}

backend.json
{
    "name": "backend", 
    "description": "Simulates being the backend - wait for middle to connect and just echo back the received data",
    "log_level": 10,
    "BackendHostThread": false,
    "BackendHostPort": 0,
    "ListenHostThread": true,
    "ListenHostPort": 4243,
    "CommandThreadPort": 8079,
    "filter": "echo"
}


3: The original prompt
The CO-pilot communication application.
Can you help me write a communication application with the following characteristics in python
all configuration information is read from a json file passed to the program as argv[1].  if no arguments is passed use filename config.json as default.

1. Assumptions:
    1. All socket communication follows a protocol where first a length field is received. 
    2. A config parameter tells which type_of_length field one of the following 2
    3. 1: ascii_4 meaning 4 bytes in ascii telling the length of the actual data to follow.
    4. 2: binary_4 meaning 4 bytes binary in big endian formats has length of the actual data to follow
    5. Socket communication must be non blocking i.e. use the set time out to 0.5 seconds for the socket. 
    6. For logging use standard python logging

2. QueueObject class.
    1. There exists a QueueObject class defining a queue object similar to the python queue class.
    2. The class constructor is initiated with a name plus a dictionary.holding configuration information.
    3. The class implements:
    4. put  a function for sending data taking as input a byte array
    5. get a function receiving data taking as input a timeout parameter in milliseconds - the routing returns a byte array if data was received or None if no data received

3. Messge class
    1. Holds dictionary 
    2. msg = { 
    3.    "data_base64": string, 
    4.    "time_created_ns": int
    5. }
    6. Constructor takes "data" as variable a byte array as argument and creates data_base64 as the base64 encoding of the byte array the time_created_ns is the timestamp for the transaction in nano seconds ie when Message object is created
    7. The class exposes 
    8. get_data returns data_base64 as byte array after base64 decoding-
    9. get_json returns the msg dictionary as as json object
    10. get_create_ns returns the int time_create_ns

4. MessageString class
    1. An extension of message class
    2. Constructor takes string as input. 
    3. The string  is encoded to bytes utf-8 and then stored in the message class as data_base64 base64 encoded.
    4. Exposes get_string returning the data_base64 after converting to byte array and then to utf-8 string

5. Filter class
    1. A filter is constructed with a name and a  run_function which is a python function.
    2. The filter exposes a function "run" taking as input message a Message object and returning an updated Message object.
    3. Exposes a function get_name returning the name of the filter passed in the constructor.


6. CommunicationApplication class
    1. The place where it all starts.
    2. the Constructor of the class is called with a dictionary - the result of reading the config file above. This dictionary is stored in self.config.
    
    3. all functionality assembled in a class CommunicationApplication
    
    4. The class contains a dictionary "filters" containing name as key and an object of the type Filter. 
    5. The class exposes an add_filter function taking a Filter object as input and stores it to the filters dictionary with the Filter.get_name() as key.
    6. The class exposes an get_filter function taking name as input looks up if name exists in filters and if so returns the Filter Object - if not found returns None
    
    7. The class contains a dictionary "queues" containing name as key and an object of the type QueueObject. 
    8. The class exposes method add_queue taking name as input and looks up in "queues" if it exist then returns the QueueObject from the dictionary. If not found then a new QueueObject with the given name is created, stored in "queues" and returned to the caller.

7. CommunicationThread: 

    1. The communication is done with a number of threads all sharing the following setup
    2. A new CommunicationThread is defined as an extension of python thread.
    3. All threads will be extensions of CommunicationThread 
    4. All threads are in held in a list named "threads"in the CommunicationApplication class.
    5. A thread should be added to this list before it is started.
    
    6. Constructor of CommunicationThread takes name, queue_name, exit_if_inactive and filter_name as input -  filter_name has a default value of None.
    7. The object has the following attributes.
        a. heartbeat initiated to current time
        b. active initiated to True
        c. queue initiated by calling the CommunicationApplication.add_queue(self.queue_name)
        d. filter initiated by calling the CommunicationApplication.get_filter(filter_name). 
    8. A thread will typically have a "While true" loop and in the beginning of this loop the thread should update the heartbeat field with the current time. 
    9. If filter <> None the filter.run method should be called with message as parameter just before sending data 
    10. the "BigMama" Thread can set this Boolean to False if it wants the thread to stop. 
    11. Some threads will be waiting for commands from a queue. A command is just a text string received from a QueueObject.
8. SocketReceiverThread
    1. An extension of the CommunicationThread receiving data on a socket creating a message object and passing it on to a QueueObject.
    2. Constructor takes arguments, with socket, length_field_type, queue_name, exit_if_inactive and filter_name 
    3. Enters a while active loop receiving data from the socket
        a. Update heartbeat.
        b. Receives 4 bytes and based on length_field_type calculates the length in bytes of the data to follow.
        c. If length field is received then 
            i. receives length data bytes to variable data a byte array 
            ii. Constructs a  Message from the  data variable and sends it to the queue.
        d.  
9. SocketSenderThread
    1. An extension of the CommunicationThread receiving data from queue and sending data on socket.
    2. Constructor takes arguments, with socket, length_field_type, queue_name, exit_if_inactive and filter_name 
    3. Enters a while active loop receiving data from the queue
        a. Update heartbeat.
        b. If data is received from queue 
            i. Creates a length field according to length field_type and sends on the socket.
            ii. Gets the data as byte array from message and sends this byte array on the socket
        c.  
    4. 
10. big_mama thread 
    1. Initiated by CommunicationApplication with queue_name="big_mama", exit_if_inactive=True and filter_name=None
    2. The thread is monitoring that all other threads are alive and if a thread with exit_if_inactive is not reporting in time then stops all threads and exits the program
    3. All threads must be non blocking an report a heartbeat at least once every 0.5 seconds.
    4. if a thread has not reported in 30 seconds it is considered inactive and will be stopped.
    5. When a thread is having problems an alert should be sent to the log.
    6. When program exiting an alert should be sent to the log.
    7. big_mama starts the following threads which will be described further down
        a. backend_host thread
        b. listen_client 
        c. command_thread
    8. after having started the threads big mama enters a "while active" loop where it receives commands from the internal big_mama queue it will time out on receive every 0.2 seconds. 
    9. when the command stop is received then big_mama will set the active attribute in all threads to False
    10. after having set all threads to False big_mama will loop through threads every 0,5 second for a maximum of 10 seconds until they are no longer active. 
    11. After this big_mama exits the program. 

11. Backend_host thread
12. Initiated with queue_name="backend_host", exit_if_inactive=True and filter_name=None
13. Creates a socket connects to backend server localhost on port 4243 and starts
    1. host_receiver - a SocketReceiverThread initiated with socket, length_field_type=binary_4, queue_name=host_receiver, exit_if_inactive=True and filter_name=host_receiver
    2. host sender -a SocketSenderThread initiated with socket, length_field_type=binary_4, queue_name=host_sender, exit_if_inactive=True and filter_name=host_sender
14. enters into a loop
    1.  waiting for commands in queue backend_host
    2. If command received and = "stop" is received then the thread ends. 

15. Listen_client thread
    1. Initiated with queue_name="listen_client", exit_if_inactive=True and filter_name=None
    2. Starts with looping while waiting for client to connect:
        a. Listens on port 4242 for clients to connect to a socket  
        b. Here the socket will time out if no client and the heartbeat can be updated
        c. When client connects it is accepted and the following threads started 
            i. host_receiver - a SocketReceiverThread initiated with socket, length_field_type=ascii_4, queue_name=from_client, exit_if_inactive=True and filter_name=host_receiver
            ii. host sender -a SocketSenderThread initiated with socket, length_field_type=ascii_4, 9queue_name=to_client, exit_if_inactive=True and filter_name=host_sender
            iii. a configurable (NUM_WORKERS) number of worker threads named worker_x where x is from 1 to NUM_WORKERS s for initial application set NUM_WORKERS=3
        d. When thread have been started the loop ends
    3. Enters into a new loop waiting for commands in queue listen_client. If the command="stop" is received then the thread ends. 
    
16. worker threads
    1. Initiated with queue_name = "from_client", exit_if_inactive=False and filter_name="from_client"
    2. The worker threads reads messages from queue and applies the filter and then sends the data to queue "host_sender"

17. command_thread
    1. Initiated with queue_name=command, exit_if_inactive=True and filter_name=None
    2. Command_thread is a thread exposing a RESTAPI on port 8079.  It will listen for a client - accept the client and process the request.
    3. The allowed request is /command/stop{queue}
    4. when received the api will create a MessageString and send to the QueueObject named in the parameter  {queue}. 
    5. This command can be used for stopping a routine from the outside.

4: The Original code after my adjustment
import sys
import json
import socket
import threading
import time
import base64
import logging
import cgi

from queue import Queue
from http.server import BaseHTTPRequestHandler, HTTPServer

# Setup logging
logging.basicConfig(level=logging.INFO)

# QueueObject class
class QueueObject:
    def __init__(self, name, config):
        self.name = name
        self.config = config
        self.queue = Queue()

    def put(self, data):
        self.queue.put(data)

    def get(self, timeout):
        try:
            return self.queue.get(timeout=timeout / 1000)
        except:
            return None

# Message class
class Message:
    def __init__(self, data):
        self.msg = {
            "data_base64": base64.b64encode(data).decode('utf-8'),
            "time_created_ns": time.time_ns()
        }

    def get_data(self):
        return base64.b64decode(self.msg["data_base64"])

    def get_json(self):
        return self.msg

    def get_create_ns(self):
        return self.msg["time_created_ns"]

# MessageString class
class MessageString(Message):
    def __init__(self, string):
        super().__init__(string.encode('utf-8'))

    def get_string(self):
        return self.get_data().decode('utf-8')

# Filter class
class Filter:
    def __init__(self, name, run_function):
        self.name = name
        self.run_function = run_function

    def run(self, message):
        return self.run_function(message)

    def get_name(self):
        return self.name

# CommunicationApplication class
class CommunicationApplication:
    def __init__(self, config):
        self.config = config
        self.filters = {}
        self.queues = {}
        self.threads = []

    def add_filter(self, filter_obj):
        self.filters[filter_obj.get_name()] = filter_obj

    def get_filter(self, name):
        return self.filters.get(name, None)

    def add_queue(self, name):
        if name not in self.queues:
            self.queues[name] = QueueObject(name, self.config)
        return self.queues[name]

# CommunicationThread class
class CommunicationThread(threading.Thread):
    def __init__(self, name, queue_name, exit_if_inactive, filter_name=None):
        super().__init__()
        self.name = name
        self.queue_name = queue_name
        self.exit_if_inactive = exit_if_inactive
        self.filter_name = filter_name
        self.heartbeat = time.time()
        self.active = True
        self.queue = app.add_queue(self.queue_name)
        self.filter = app.get_filter(self.filter_name)

    def run(self):
        while self.active:
            self.heartbeat = time.time()
            time.sleep(0.5)

# SocketReceiverThread class
class SocketReceiverThread(CommunicationThread):
    def __init__(self, name, socket, length_field_type, queue_name, exit_if_inactive, filter_name=None):
        super().__init__(name, queue_name, exit_if_inactive, filter_name)
        self.socket = socket
        self.length_field_type = length_field_type

    def run(self):
        while self.active:
            self.heartbeat = time.time()
            try:
                length_field = self.socket.recv(4)
                if self.length_field_type == 'ascii_4':
                    length = int(length_field.decode('ascii'))
                elif self.length_field_type == 'binary_4':
                    length = int.from_bytes(length_field, 'big')
                data = self.socket.recv(length)
                message = Message(data)
                if self.filter:
                    message = self.filter.run(message)
                self.queue.put(message)
            except:
                pass
            time.sleep(0.5)

# SocketSenderThread class
class SocketSenderThread(CommunicationThread):
    def __init__(self, name, socket, length_field_type, queue_name, exit_if_inactive, filter_name=None):
        super().__init__(name, queue_name, exit_if_inactive, filter_name)
        self.socket = socket
        self.length_field_type = length_field_type

    def run(self):
        while self.active:
            self.heartbeat = time.time()
            message = self.queue.get(500)
            if message:
                data = message.get_data()
                length = len(data)
                if self.filter:
                    message = self.filter.run(message)
                if self.length_field_type == 'ascii_4':
                    length_field = f"{length:04}".encode('ascii')
                elif self.length_field_type == 'binary_4':
                    length_field = length.to_bytes(4, 'big')
                self.socket.send(length_field)
                self.socket.send(data)
            time.sleep(0.5)

# BigMamaThread class
class BigMamaThread(CommunicationThread):
    def __init__(self, name, queue_name, exit_if_inactive, filter_name=None):
        super().__init__(name, queue_name, exit_if_inactive, filter_name)

    def run(self):
        while self.active:
            self.heartbeat = time.time()
            for thread in app.threads:
                if time.time() - thread.heartbeat > 30:
                    if thread.exit_if_inactive:
                        thread.active = False
                        logging.warning(f"Thread {thread.name} is inactive and will be stopped.")
            time.sleep(0.5)

# BackendHostThread class
class BackendHostThread(CommunicationThread):
    def __init__(self, name, queue_name, port, exit_if_inactive, filter_name=None):
        super().__init__(name, queue_name, exit_if_inactive, filter_name)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.settimeout(10)
        self.port=port
        logging.info(f'{self.name} connecting to {self.port}')
        self.socket.connect(('localhost', port))
        logging.info(f'{self.name} connectedto {self.port}')
        length_field_type = 'ascii_4'

        self.receiver_thread = SocketReceiverThread('host_receiver', self.socket, length_field_type, 'host_receiver', True, 'host_receiver')
        self.sender_thread = SocketSenderThread('host_sender', self.socket, length_field_type, 'host_sender', True, 'host_sender')
        app.threads.append(self.receiver_thread)
        app.threads.append(self.sender_thread)

    def run(self):
        self.receiver_thread.start()
        self.sender_thread.start()
        while self.active:
            self.heartbeat = time.time()
            command = self.queue.get(500)
            if command and command.get_string() == 'stop':
                self.active = False
                self.receiver_thread.active = False
                self.sender_thread.active = False

# FrontendThread class
class FrontendThread(CommunicationThread):
    def __init__(self, name, queue_name, port, exit_if_inactive, filter_name=None):
        super().__init__(name, queue_name, exit_if_inactive, filter_name)
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        logging.info(f'{self.name} Listening for client on {self.port}')
        
    def run(self):
        length_field_type = 'ascii_4'
        self.socket.bind(('localhost', self.port))
        while self.active:
            logging.debug(f'run still {self.name} Listening for client on {self.port}')
            self.heartbeat = time.time()
            self.socket.settimeout(5)
            self.socket.listen(10)  # max backlog of 10... not really needed.. 

            try:
                client_socket, _ = self.socket.accept()
                client_socket.settimeout(5)

                logging.info(f'Client accepted by {self.name}')

                receiver_thread = SocketReceiverThread('client_receiver', client_socket, length_field_type, 'from_client', True, 'client_receiver')
                sender_thread = SocketSenderThread('client_sender', client_socket, length_field_type, 'to_client', True, 'client_sender')
                app.threads.append(receiver_thread)
                app.threads.append(sender_thread)
                receiver_thread.start()
                sender_thread.start()
                for i in range(3):
                    worker_thread = CommunicationThread(f'worker_{i+1}', 'from_client', False, 'from_client')
                    app.threads.append(worker_thread)
                    worker_thread.start()
                break
            except:
                pass
            time.sleep(0.5)
        while self.active:
            logging.debug(f'Listener waitin for commands {self.name}')
            self.heartbeat = time.time()
            command = self.queue.get(10000)
            if command and command.get_string() == 'stop':
                self.active = False

# CommandThread class
class CommandThread(CommunicationThread):
    def __init__(self, name, queue_name, port, exit_if_inactive, filter_name=None):
        super().__init__(name, queue_name, exit_if_inactive, filter_name)
        self.port = port
    def run(self):
        logging.info(f'command server started on {self.port}')
        server = HTTPServer(('localhost', self.port), CommandHandler)
        server.timeout = 5
        while self.active:
            self.heartbeat = time.time()
            logging.debug("Command ready")
            server.handle_request()


# taken from https://gist.github.com/nitaku/10d0662536f37a087e1b
class CommandHandler(BaseHTTPRequestHandler):
    def setup(self):
        BaseHTTPRequestHandler.setup(self)
        self.request.settimeout(10)

    def _set_headers(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        
    def do_HEAD(self):
        self._set_headers()

# POST echoes the message adding a JSON fields
    def do_POST(self):
        length = int(self.headers.get('Content-Length'))
        message = json.loads(self.rfile.read(length))
        msg2 = json.loads(message)  # TBD why do we need 2 json.loads ? 
        # add a property to the object, just to mess with data
        msg2["received"] = "ok"
        return_msg = json.dumps(msg2)
        # send the message back
        self._set_headers()
        self.wfile.write(return_msg.encode())

    def do_GET(self):
        logging.info("received" + str(self.path))
        last_part =  self.path.split('/')[-1]


        if self.path.startswith('/command/stop'):
            queue_name = self.path.split('/')[-1]
            message = MessageString('stop')
            app.add_queue(queue_name).put(message)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'Command received')
        else:
            self.send_response(404)
            self.end_headers()

# Main function
if __name__ == "__main__":
    config_file = sys.argv[1] if len(sys.argv) > 1 else 'config.json'
    with open(config_file, 'r') as f:
        config = json.load(f)

    app = CommunicationApplication(config)

    big_mama_thread = BigMamaThread('big_mama', 'big_mama', True)
    app.threads.append(big_mama_thread)
    big_mama_thread.start()

    if (config['BackendHostThread']):
        backend_host_thread = BackendHostThread('backend_host', 'backend_host', config['BackendHostPort'], True)
        app.threads.append(backend_host_thread)
        backend_host_thread.start()

    if (config['ListenHostThread']):
        listen_client_thread = FrontendThread('listen_client', 'listen_client', config['ListenHostPort'], True)
        app.threads.append(listen_client_thread)
        listen_client_thread.start()

    command_thread = CommandThread('command_thread', 'command', config['CommandThreadPort'], True)
    app.threads.append(command_thread)
    command_thread.start()

# curl http://localhost:8009
#{"received": "ok", "hello": "world"}

#curl --data "{\"this\":\"is a test\"}" --header "Content-Type: application/json" http://localhost:8009
# {"this": "is a test", "received": "ok"}
